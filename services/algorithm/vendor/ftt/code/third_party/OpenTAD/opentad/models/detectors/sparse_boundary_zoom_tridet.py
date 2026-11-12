"""Sparse raw-frame boundary zoom for end-to-end TriDet.

The coarse detector still processes 768 stride-4 frames. A shared, small RGB
encoder reads five native frames around at most K selected boundaries, and
predicts a bounded correction in native frames. The zoom branch and detector
are optimized together. Selection of crop locations is discrete; no gradient
is claimed through video decoding or top-k selection.
"""
import os
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from decord import VideoReader, cpu

from ..builder import DETECTORS
from .tridet import TriDet


class BoundaryZoom(nn.Module):
    def __init__(self, channels=512):
        super().__init__()
        self.image = nn.Sequential(
            nn.Conv2d(3, 16, 5, stride=2, padding=2), nn.ReLU(inplace=True),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1),
        )
        self.coarse = nn.Sequential(nn.LayerNorm(channels), nn.Linear(channels, 64), nn.ReLU())
        self.fusion = nn.Sequential(nn.Linear(5 * 64 + 64 + 1, 128), nn.ReLU(), nn.Linear(128, 1))
        # The detector initially reproduces the unchanged coarse predictions.
        nn.init.zeros_(self.fusion[-1].weight)
        nn.init.zeros_(self.fusion[-1].bias)

    def forward(self, frames, coarse_features, kind):
        # frames: [N, 5, 3, 64, 64]; each temporal position shares weights.
        n = frames.shape[0]
        z = self.image(frames.reshape(n * 5, 3, 64, 64)).flatten(1).reshape(n, -1)
        h = self.coarse(coarse_features)
        return 4.0 * torch.tanh(self.fusion(torch.cat([z, h, kind[:, None]], 1)).squeeze(-1))


@DETECTORS.register_module()
class SparseBoundaryZoomTriDet(TriDet):
    def __init__(self, projection, rpn_head, neck=None, backbone=None, zoom_topk=8,
                 zoom_train_gt=8, zoom_loss_weight=0.15):
        super().__init__(projection, rpn_head, neck=neck, backbone=backbone)
        self.zoom = BoundaryZoom(channels=projection.out_channels)
        self.zoom_topk = int(zoom_topk)
        self.zoom_train_gt = int(zoom_train_gt)
        self.zoom_loss_weight = float(zoom_loss_weight)
        self._readers = {}
        self.zoom_offsets = np.array([-4, -2, 0, 2, 4], dtype=np.int64)

    def _reader(self, meta):
        path = os.path.join(meta['data_path'], meta['video_name'] + '.mp4')
        if path not in self._readers:
            # The validation loader revisits the same video for multiple windows.
            if len(self._readers) >= 2:
                self._readers.pop(next(iter(self._readers)))
            self._readers[path] = VideoReader(path, ctx=cpu(0), width=64, height=64, num_threads=1)
        return self._readers[path]

    def _raw_frames(self, meta, positions, device):
        vr = self._reader(meta)
        stride = int(meta['snippet_stride'])
        origin = float(meta.get('window_start_frame', 0)) + float(meta.get('offset_frames', 0))
        idx = np.rint(positions.detach().cpu().numpy() * stride + origin).astype(np.int64)
        idx = np.clip(idx[:, None] + self.zoom_offsets[None, :], 0, len(vr) - 1)
        # One decoder call for all selected boundaries, including duplicates.
        unique, inverse = np.unique(idx.reshape(-1), return_inverse=True)
        raw = vr.get_batch(unique.tolist()).asnumpy()
        raw = raw[inverse].reshape(len(positions), 5, 64, 64, 3)
        return torch.from_numpy(raw.copy()).to(device=device, non_blocking=True).permute(0, 1, 4, 2, 3).float().div_(255.0)

    @staticmethod
    def _at_positions(feat, positions):
        # Linear interpolation keeps gradients to coarse features and proposal positions.
        p = positions.clamp(0, feat.shape[-1] - 1)
        lo = p.floor().long()
        hi = (lo + 1).clamp(max=feat.shape[-1] - 1)
        alpha = (p - lo).unsqueeze(-1)
        return feat[:, lo].transpose(0, 1) * (1 - alpha) + feat[:, hi].transpose(0, 1) * alpha

    def _zoom(self, feat, meta, starts, ends):
        if starts.numel() == 0:
            return starts, ends
        pos = torch.stack((starts, ends), dim=1).flatten()
        frames = self._raw_frames(meta, pos, feat.device)
        coarse = self._at_positions(feat, pos)
        kind = torch.arange(pos.numel(), device=feat.device).remainder(2).to(coarse.dtype)
        delta = self.zoom(frames, coarse, kind).reshape(-1, 2)
        return delta[:, 0], delta[:, 1]

    def forward_train(self, inputs, masks, metas, gt_segments, gt_labels, iv2_feats=None, **kwargs):
        x = self.backbone(inputs) if self.with_backbone else inputs
        x = self.concat_iv2(x, iv2_feats)
        if self.with_projection:
            x, masks = self.projection(x, masks)
        if self.with_neck:
            x, masks = self.neck(x, masks)
        losses = self.rpn_head.forward_train(x, masks, gt_segments=gt_segments, gt_labels=gt_labels, **kwargs)
        zoom_losses = []
        for bi, gt_cpu in enumerate(gt_segments):
            gt = gt_cpu.to(device=x[0].device, dtype=x[0].dtype)
            if gt.numel() == 0:
                continue
            choice = torch.randperm(len(gt), device=gt.device)[:self.zoom_train_gt]
            gt = gt[choice]
            # Teacher-forced proposal locations during early training; detector and zoom
            # parameters still receive gradients from the shared joint objective.
            jitter = (torch.rand_like(gt) * 2 - 1).clamp(-1, 1)
            coarse = gt + jitter
            coarse[:, 0] = coarse[:, 0].clamp(min=0, max=x[0].shape[-1] - 1)
            coarse[:, 1] = coarse[:, 1].clamp(min=0, max=x[0].shape[-1] - 1)
            ds, de = self._zoom(x[0][bi], metas[bi], coarse[:, 0], coarse[:, 1])
            stride = float(metas[bi]['snippet_stride'])
            target = ((gt - coarse) * stride).clamp(-4, 4)
            pred = torch.stack([ds, de], dim=-1)
            zoom_losses.append(F.smooth_l1_loss(pred / 4, target / 4))
        losses['zoom_loss'] = self.zoom_loss_weight * torch.stack(zoom_losses).mean() if zoom_losses else x[0].sum() * 0
        losses['cost'] = sum(losses.values())
        return losses

    def forward_test(self, inputs, masks, metas=None, infer_cfg=None, iv2_feats=None, **kwargs):
        x = self.backbone(inputs) if self.with_backbone else inputs
        x = self.concat_iv2(x, iv2_feats)
        x, masks = self.pad_data(x, masks)
        if self.with_projection:
            x, masks = self.projection(x, masks)
        if self.with_neck:
            x, masks = self.neck(x, masks)
        points, reg, scores = self.rpn_head.forward_test(x, masks, **kwargs)
        reg = reg.clone()
        for bi, meta in enumerate(metas):
            flat = scores[bi].flatten()
            nclass = scores.shape[-1]
            # Select a few high-scoring, nonduplicate class proposals per window.
            order = flat.topk(min(128, flat.numel())).indices
            picks = []
            segments = []
            for z in order:
                pi = int(z.item() // nclass)
                ci = int(z.item() % nclass)
                seg = self.rpn_head.get_proposals(points[pi:pi + 1], reg[bi, ci, pi:pi + 1])[0]
                if not torch.isfinite(seg).all() or seg[1] <= seg[0]:
                    continue
                duplicate = False
                for old_pi, old_ci, old_seg in segments:
                    if old_ci != ci:
                        continue
                    inter = max(0.0, min(float(seg[1]), float(old_seg[1])) - max(float(seg[0]), float(old_seg[0])))
                    union = max(float(seg[1]), float(old_seg[1])) - min(float(seg[0]), float(old_seg[0]))
                    if union > 0 and inter / union > 0.7:
                        duplicate = True
                        break
                if not duplicate:
                    picks.append((pi, ci))
                    segments.append((pi, ci, seg))
                if len(picks) >= self.zoom_topk:
                    break
            if not picks:
                continue
            starts = torch.stack([p[2][0] for p in segments])
            ends = torch.stack([p[2][1] for p in segments])
            ds, de = self._zoom(x[0][bi], meta, starts, ends)
            stride = float(meta['snippet_stride'])
            for j, (pi, ci) in enumerate(picks):
                scale = stride * float(points[pi, 3])
                reg[bi, ci, pi, 0] -= ds[j] / scale
                reg[bi, ci, pi, 1] += de[j] / scale
        return points, reg, scores
