"""TriDet with a separate, multi-scale localization pathway for two video streams."""

import torch
import torch.nn as nn
import torch.nn.functional as F

from opentad.models.builder import DETECTORS
from opentad.models.detectors.tridet import TriDet


class DualStreamBoundaryPath(nn.Module):
    """Build localization features from IV2/V-JEPA temporal changes at every FPN scale."""

    def __init__(self, stream_channels=(3200, 1408), channels=512, hidden=128, levels=6):
        super().__init__()
        self.stream_channels = tuple(stream_channels)
        self.embed = nn.ModuleList([nn.Conv1d(c, hidden, 1) for c in stream_channels])
        self.change_embed = nn.Conv1d(4 * hidden, channels, 1)
        self.temporal = nn.ModuleList([
            nn.Sequential(
                nn.Conv1d(channels, channels, 3, padding=2 ** min(i, 2),
                          dilation=2 ** min(i, 2), groups=channels),
                nn.GELU(),
                nn.Conv1d(channels, channels, 1),
            ) for i in range(levels)
        ])
        self.lateral = nn.ModuleList([nn.Conv1d(channels, channels, 1) for _ in range(levels)])
        self.topdown = nn.ModuleList([nn.Conv1d(channels, channels, 1) for _ in range(levels - 1)])
        self.output = nn.ModuleList([nn.Conv1d(channels, channels, 1) for _ in range(levels)])
        for layer in self.output:
            nn.init.zeros_(layer.weight)
            nn.init.zeros_(layer.bias)

    def forward(self, raw, semantic, masks, mean, scale):
        valid = masks[0].unsqueeze(1)
        x = (raw - mean.to(raw.dtype)) * scale.to(raw.dtype) * valid.to(raw.dtype)
        streams = [F.gelu(layer(part)) for layer, part in zip(self.embed, x.split(self.stream_channels, dim=1))]
        changes = []
        for s in streams:
            changes.extend((s - F.pad(s[..., :-1], (1, 0), mode="replicate"),
                            s - F.pad(s[..., 1:], (0, 1), mode="replicate")))
        boundary = F.gelu(self.change_embed(torch.cat(changes, dim=1)))
        boundary = boundary * valid.to(boundary.dtype)
        levels = []
        for i, sem in enumerate(semantic):
            evidence = F.adaptive_avg_pool1d(boundary, sem.shape[-1])
            levels.append(self.temporal[i](evidence) + self.lateral[i](sem))
        for i in range(len(levels) - 2, -1, -1):
            levels[i] = levels[i] + self.topdown[i](F.interpolate(levels[i + 1], size=levels[i].shape[-1], mode="nearest"))
        return [sem + layer(F.gelu(loc)) * mask.unsqueeze(1).to(sem.dtype)
                for sem, loc, mask, layer in zip(semantic, levels, masks, self.output)]


@DETECTORS.register_module()
class DualPathBoundaryTriDet(TriDet):
    """Semantic FPN drives classes; dual-stream change FPN drives localization."""

    def __init__(self, projection, rpn_head, neck=None, backbone=None, boundary_hidden=128):
        super().__init__(projection, rpn_head, neck=neck, backbone=backbone)
        self.boundary_path = DualStreamBoundaryPath(
            stream_channels=self.projection.stream_channels,
            channels=rpn_head.in_channels,
            hidden=boundary_hidden,
            levels=len(rpn_head.prior_generator.strides),
        )

    def _features(self, inputs, masks, iv2_feats, test):
        x = self.backbone(inputs) if self.with_backbone else inputs
        raw = self.concat_iv2(x, iv2_feats)
        if test or not self.training:
            raw, masks = self.pad_data(raw, masks)
        semantic, masks = self.projection(raw, masks)
        if self.with_neck:
            semantic, masks = self.neck(semantic, masks)
        localization = self.boundary_path(raw, semantic, masks, self.projection.feat_mean, self.projection.feat_scale)
        return (semantic, localization), masks

    def forward_train(self, inputs, masks, metas, gt_segments, gt_labels, iv2_feats=None, **kwargs):
        features, masks = self._features(inputs, masks, iv2_feats, False)
        losses = self.rpn_head.forward_train(features, masks, gt_segments=gt_segments, gt_labels=gt_labels, **kwargs)
        losses["cost"] = sum(losses.values())
        return losses

    def forward_test(self, inputs, masks, metas=None, infer_cfg=None, iv2_feats=None, **kwargs):
        features, masks = self._features(inputs, masks, iv2_feats, True)
        return self.rpn_head.forward_test(features, masks, **kwargs)
