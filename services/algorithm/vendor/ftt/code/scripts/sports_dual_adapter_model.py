"""Two-level TriDet with online VideoMAEv2-G and V-JEPA2.1 adapters.

The video encoders share their input frames. Only their internal adapters,
the temporal projection, the two detection heads, and the soft relation layer
are trainable. This module is intentionally independent of the OpenTAD
single-label dataset interface.
"""

from __future__ import annotations

import torch
from mmengine.config import ConfigDict
from torch import nn
from torch.nn import functional as F

from opentad.models.backbones.dual_backbone_wrapper import DualBackboneWrapper
from opentad.models.bricks import SGPBlock
from opentad.models.dense_heads.tridet_head import TriDetHead
from opentad.models.necks.fpn import FPNIdentity
from opentad.models.projections.tridet_proj import TriDetProj

from sports_soft_parent_link import SoftParentLink, association_loss


class TaskPyramid(nn.Module):
    """Six residual temporal refinements, one parameter set per task."""

    def __init__(self):
        super().__init__()
        self.blocks = nn.ModuleList([
            nn.Sequential(nn.Conv1d(512, 512, 3, padding=1, groups=512),
                          nn.GELU(), nn.Conv1d(512, 512, 1))
            for _ in range(6)])
        self.scale = nn.Parameter(torch.tensor(0.1))

    def forward(self, feats, masks):
        return [((feat + self.scale * block(feat)) * mask[:, None, :])
                for feat, mask, block in zip(feats, masks, self.blocks)]


class UniformScaleExchange(nn.Module):
    """G-style coarse-to-fine context with equal weight across six levels."""

    def __init__(self):
        super().__init__()
        self.proj = nn.Conv1d(512, 512, 1)
        self.scale = nn.Parameter(torch.tensor(0.1))

    def forward(self, fine, coarse, masks):
        result = []
        for target, mask in zip(fine, masks):
            sources = torch.stack([
                F.interpolate(feat.detach().float(), size=target.shape[-1],
                              mode="linear", align_corners=False)
                for feat in coarse], dim=1)
            context = sources.mean(dim=1).to(target.dtype)
            result.append((target + self.scale * self.proj(context)) * mask[:, None, :])
        return result


def make_head(num_classes):
    return TriDetHead(
        num_classes=num_classes, in_channels=512, feat_channels=512,
        num_convs=2, cls_prior_prob=.01,
        prior_generator=dict(
            type="PointGenerator", strides=[1, 2, 4, 8, 16, 32],
            regression_range=[(0, 4), (4, 8), (8, 16),
                              (16, 32), (32, 64), (64, 10000)]),
        loss_normalizer=100, loss_normalizer_momentum=.9,
        center_sample="radius", center_sample_radius=1.5,
        label_smoothing=0, boundary_kernel_size=3,
        iou_weight_power=.2, num_bins=16,
        loss=ConfigDict(cls_loss=dict(type="FocalLoss"),
                        reg_loss=dict(type="DIOULoss"),
                        iou_rate=dict(type="GIOULoss")),
    )


def candidate_match(segments, labels, gt_segments, gt_labels, min_iou=.5,
                    ignored_gt=None):
    """Class-aware maximum-tIoU matching, returning GT index or -1."""
    if segments.numel() == 0 or gt_segments.numel() == 0:
        return torch.full((len(segments),), -1, device=segments.device, dtype=torch.long)
    left = torch.maximum(segments[:, None, 0], gt_segments[None, :, 0])
    right = torch.minimum(segments[:, None, 1], gt_segments[None, :, 1])
    inter = (right - left).clamp_min(0)
    seg_len = (segments[:, 1] - segments[:, 0]).clamp_min(0)
    gt_len = (gt_segments[:, 1] - gt_segments[:, 0]).clamp_min(0)
    iou = inter / (seg_len[:, None] + gt_len[None, :] - inter).clamp_min(1e-6)
    iou = iou.masked_fill(labels[:, None] != gt_labels[None, :], -1)
    if ignored_gt is not None:
        iou = iou.masked_fill(ignored_gt[None, :], -1)
    best_iou, best = iou.max(dim=1)
    return torch.where(best_iou >= min_iou, best,
                       torch.full_like(best, -1))


class SportsDualAdapterTriDet(nn.Module):
    def __init__(self, backbone_cfg, num_coarse, num_fine, *, window_length=768,
                 max_actions=256, max_parents=64):
        super().__init__()
        self.window_length = window_length
        self.max_actions = max_actions
        self.max_parents = max_parents
        self.feature_mode_smoke = backbone_cfg is None
        self.backbone = None if self.feature_mode_smoke else DualBackboneWrapper(backbone_cfg)
        self.projection = TriDetProj(
            in_channels=2816, out_channels=512, sgp_mlp_dim=768,
            arch=(2, 2, 5), sgp_win_size=[1] * 6,
            downsample_type="max", k=5, init_conv_vars=0,
            conv_cfg=dict(kernel_size=3), norm_cfg=dict(type="LN"),
            path_pdrop=.1, use_abs_pe=False, max_seq_len=window_length,
            input_noise=.0005)
        self.neck = FPNIdentity(in_channels=512, out_channels=512, num_levels=6)
        self.coarse_head = make_head(num_coarse)
        self.fine_head = make_head(num_fine)
        # G's initialization revives both original SGP multiplication paths
        # while preserving a zero initial product at the branch output.
        for block in self.projection.modules():
            if isinstance(block, SGPBlock):
                nn.init.normal_(block.psi.weight, 0.0, .02)
                nn.init.zeros_(block.psi.bias)
                nn.init.normal_(block.global_fc.weight, 0.0, .02)
                nn.init.zeros_(block.global_fc.bias)
        self.rally_pyramid = TaskPyramid()
        self.action_pyramid = TaskPyramid()
        self.exchange = UniformScaleExchange()
        self.relation = SoftParentLink(input_dim=512, hidden_dim=128)

    def encode(self, frames, masks):
        if masks.shape != (frames.shape[0], self.window_length):
            raise ValueError("Expected one valid-frame mask per video window")
        if self.feature_mode_smoke:
            if frames.ndim != 3:
                raise ValueError("Feature smoke mode expects [B,2816,T]")
            x = frames
        else:
            if frames.ndim != 6 or frames.shape[1] != 1:
                raise ValueError("Expected video tensor [B,1,3,T,H,W]")
            x = self.backbone(frames, masks)
        if x.shape[1:] != (2816, self.window_length):
            raise ValueError(f"Unexpected dual-adapter feature shape: {tuple(x.shape)}")
        feats, feat_masks = self.projection(x, masks)
        return self.neck(feats, feat_masks)

    @staticmethod
    def _candidates(head, prediction, high_res_features, batch_idx, limit):
        points, offsets, scores = prediction
        score = scores[batch_idx]
        n_points, n_classes = score.shape
        flat = score.reshape(-1)
        k = min(limit, flat.numel())
        values, indices = torch.topk(flat, k)
        valid = values > 0.001
        values, indices = values[valid], indices[valid]
        point_id = torch.div(indices, n_classes, rounding_mode="floor")
        labels = indices.remainder(n_classes)
        if point_id.numel() == 0:
            return (points.new_zeros((0, 2)), labels, values,
                    high_res_features.new_zeros((0, high_res_features.shape[1])))
        selected_offsets = offsets[batch_idx, labels, point_id]
        segments = head.get_proposals(points[point_id], selected_offsets)
        segments = segments.clamp(0, high_res_features.shape[-1])
        good = segments[:, 1] > segments[:, 0]
        segments, labels, values = segments[good], labels[good], values[good]
        # P0 has one feature per input frame. Use the predicted interval center,
        # not GT centers, for instance features during both train and inference.
        centers = ((segments[:, 0] + segments[:, 1]) / 2).long()
        centers = centers.clamp(0, high_res_features.shape[-1] - 1)
        features = high_res_features[batch_idx].transpose(0, 1)[centers]
        return segments, labels, values, features

    def task_features(self, feats, masks):
        coarse = self.rally_pyramid([f.detach() for f in feats], masks)
        fine = self.action_pyramid(feats, masks)
        return coarse, self.exchange(fine, coarse, masks)

    def predicted_relations(self, coarse_feats, fine_feats, masks,
                            *, coarse_pred=None, fine_pred=None):
        coarse_pred = coarse_pred or self.coarse_head.forward_test(coarse_feats, masks)
        fine_pred = fine_pred or self.fine_head.forward_test(fine_feats, masks)
        outputs = []
        for b in range(fine_feats[0].shape[0]):
            parents = self._candidates(self.coarse_head, coarse_pred, coarse_feats[0], b,
                                       self.max_parents)
            actions = self._candidates(self.fine_head, fine_pred, fine_feats[0], b,
                                       self.max_actions)
            logits, probabilities = self.relation(
                actions[0], parents[0], actions[2], parents[2],
                actions[3], parents[3], self.window_length)
            outputs.append(dict(actions=actions, parents=parents,
                                relation_logits=logits,
                                relation_probabilities=probabilities))
        return outputs, coarse_pred, fine_pred

    def forward(self, frames, masks, *, coarse_segments=None, coarse_labels=None,
                fine_segments=None, fine_labels=None, fine_parent_index=None,
                coarse_truncated=None, fine_truncated=None):
        feats, feat_masks = self.encode(frames, masks)
        coarse_feats, fine_feats = self.task_features(feats, feat_masks)
        if coarse_segments is None:
            return self.predicted_relations(coarse_feats, fine_feats, feat_masks)
        # A cropped event does not expose its true boundary. Overlapping
        # windows let a complete instance supervise detection elsewhere.
        det_coarse_segments = ([s[~t] for s, t in zip(coarse_segments, coarse_truncated)]
                               if coarse_truncated is not None else coarse_segments)
        det_coarse_labels = ([s[~t] for s, t in zip(coarse_labels, coarse_truncated)]
                             if coarse_truncated is not None else coarse_labels)
        det_fine_segments = ([s[~t] for s, t in zip(fine_segments, fine_truncated)]
                             if fine_truncated is not None else fine_segments)
        det_fine_labels = ([s[~t] for s, t in zip(fine_labels, fine_truncated)]
                           if fine_truncated is not None else fine_labels)
        coarse_loss = self.coarse_head.forward_train(
            coarse_feats, feat_masks, det_coarse_segments, det_coarse_labels)
        fine_loss = self.fine_head.forward_train(
            fine_feats, feat_masks, det_fine_segments, det_fine_labels)
        relations, _, _ = self.predicted_relations(coarse_feats, fine_feats, feat_masks)
        association = []
        for b, out in enumerate(relations):
            a_seg, a_cls = out["actions"][:2]
            r_seg, r_cls = out["parents"][:2]
            a_match = candidate_match(a_seg.detach(), a_cls, fine_segments[b],
                                      fine_labels[b], ignored_gt=fine_truncated[b]
                                      if fine_truncated is not None else None)
            r_match = candidate_match(r_seg.detach(), r_cls, coarse_segments[b],
                                      coarse_labels[b], ignored_gt=coarse_truncated[b]
                                      if coarse_truncated is not None else None)
            parent_index = fine_parent_index[b].clone()
            if coarse_truncated is not None:
                parent_index[coarse_truncated[b][parent_index]] = -1
            association.append(association_loss(out["relation_logits"],
                                                a_match, r_match, parent_index))
        relation_loss = torch.stack(association).mean()
        total = sum(coarse_loss.values()) + sum(fine_loss.values()) + .1 * relation_loss
        return dict(cost=total, coarse=coarse_loss, fine=fine_loss,
                    association=relation_loss)
