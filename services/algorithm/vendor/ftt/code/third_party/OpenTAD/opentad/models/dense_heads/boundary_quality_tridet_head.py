"""TriDet head with proposal-aligned boundary refinement and IoU quality ranking.

The base Trident loss and predictions are retained. A shared residual refiner
samples localization features at the two coarse boundaries; a class-specific
quality head predicts the final segment IoU for ranking. Both are trained in
the same end-to-end pass as the video adapter and detector.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from ..builder import HEADS
from .tridet_head import TriDetHead


@HEADS.register_module()
class BoundaryQualityTriDetHead(TriDetHead):
    def __init__(
        self,
        *args,
        max_refine_steps=2.0,
        refine_loss_weight=0.5,
        quality_loss_weight=0.2,
        quality_score_power=0.5,
        inference_refine=True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.max_refine_steps = float(max_refine_steps)
        self.refine_loss_weight = float(refine_loss_weight)
        self.quality_loss_weight = float(quality_loss_weight)
        self.quality_score_power = float(quality_score_power)
        self.inference_refine = bool(inference_refine)

        self.refine_mlp = nn.Sequential(
            nn.Linear(3 * self.feat_channels + 2, self.feat_channels),
            nn.ReLU(),
            nn.Linear(self.feat_channels, 2),
        )
        nn.init.zeros_(self.refine_mlp[-1].weight)
        nn.init.zeros_(self.refine_mlp[-1].bias)
        self.quality_head = nn.Conv1d(self.feat_channels, self.num_classes, kernel_size=3, padding=1)
        nn.init.normal_(self.quality_head.weight, mean=0.0, std=0.01)
        nn.init.constant_(self.quality_head.bias, -2.2)

    @staticmethod
    def _sample_feature(feat, batch_index, position):
        """Linear interpolation on one FPN level; feat is [B,F,T]."""
        length = feat.shape[-1]
        pos = position.clamp(0, length - 1)
        lo = pos.floor().long()
        hi = (lo + 1).clamp(max=length - 1)
        weight = (pos - lo).unsqueeze(-1)
        sequence = feat.transpose(1, 2)
        return sequence[batch_index, lo] * (1 - weight) + sequence[batch_index, hi] * weight

    def _refine_selected(self, feat, batch_index, time_index, coarse_offsets):
        # Stop the residual loss changing the coarse sampling coordinates. The
        # original Trident regression remains trained by its original DIOU loss.
        coarse_sample = coarse_offsets.detach()
        center = feat.transpose(1, 2)[batch_index, time_index]
        start = self._sample_feature(feat, batch_index, time_index.float() - coarse_sample[:, 0])
        end = self._sample_feature(feat, batch_index, time_index.float() + coarse_sample[:, 1])
        extra = torch.log1p(coarse_sample.clamp(min=0)).to(center.dtype)
        delta = self.refine_mlp(torch.cat([start, center, end, extra], dim=-1))
        refined = (coarse_offsets + self.max_refine_steps * torch.tanh(delta)).clamp(min=0)
        return refined

    def _dense_predictions(self, feat_list, mask_list, training):
        cls_pred, reg_pred, start_pred, end_pred = [], [], [], []
        reg_features, quality_pred = [], []
        for level, (feat, mask) in enumerate(zip(feat_list, mask_list)):
            cls_feat = feat
            reg_feat = feat
            boundary_feat = feat.detach() + self.boundary_grad_scale * (feat - feat.detach()) if training else feat.detach()
            start_feat = boundary_feat
            end_feat = boundary_feat
            for i in range(self.num_convs):
                cls_feat, _ = self.cls_convs[i](cls_feat, mask)
                reg_feat, _ = self.reg_convs[i](reg_feat, mask)
                start_feat, _ = self.cls_start_convs[i](start_feat, mask)
                end_feat, _ = self.cls_end_convs[i](end_feat, mask)
            cls_pred.append(self.cls_head(cls_feat))
            reg_pred.append(F.relu(self.scale[level](self.reg_head(reg_feat))))
            start_pred.append(self.cls_start_head(start_feat))
            end_pred.append(self.cls_end_head(end_feat))
            reg_features.append(reg_feat)
            quality_pred.append(self.quality_head(reg_feat))
        points = self.prior_generator(feat_list)
        return cls_pred, reg_pred, start_pred, end_pred, reg_features, quality_pred, points

    def _extra_losses(self, reg_pred, start_pred, end_pred, reg_features, quality_pred, mask_list, points, gt_segments, gt_labels):
        target_cls, target_reg = self.prepare_targets(points, gt_segments, gt_labels)
        target_cls = torch.stack(target_cls)
        target_reg = torch.stack(target_reg)
        valid = torch.cat(mask_list, dim=1)
        positive = (target_cls > 0.5) & valid.unsqueeze(-1)
        quality_logits = torch.cat([q.permute(0, 2, 1) for q in quality_pred], dim=1)
        quality_target = torch.zeros_like(quality_logits)
        left, right = self.prepare_out_logits(start_pred, end_pred)
        decoded = self.decode_offset([x.permute(0, 2, 1) for x in reg_pred], left, right)
        total_refine = quality_logits.sum() * 0
        level_start = 0
        all_points = torch.cat(points, dim=0)

        for feat in reg_features:
            length = feat.shape[-1]
            selected = positive[:, level_start : level_start + length, :].nonzero(as_tuple=False)
            if len(selected):
                batch = selected[:, 0]
                local_time = selected[:, 1]
                cls = selected[:, 2]
                global_time = local_time + level_start
                coarse = decoded[batch, global_time, cls]
                refined = self._refine_selected(feat, batch, local_time, coarse)
                selected_points = all_points[global_time]
                predicted_segments = self.get_proposals(selected_points, refined)
                true_segments = self.get_proposals(selected_points, target_reg[batch, global_time])
                total_refine = total_refine + self.reg_loss(predicted_segments, true_segments, reduction="sum")

                overlap = (
                    torch.minimum(predicted_segments[:, 1], true_segments[:, 1])
                    - torch.maximum(predicted_segments[:, 0], true_segments[:, 0])
                ).clamp(min=0)
                union = (
                    predicted_segments[:, 1] - predicted_segments[:, 0]
                    + true_segments[:, 1] - true_segments[:, 0] - overlap
                ).clamp(min=1e-6)
                quality_target[batch, global_time, cls] = (overlap / union).detach().to(quality_target.dtype)
            level_start += length

        normalizer = max(float(self.loss_normalizer), 1.0)
        quality_loss = self.cls_loss(quality_logits[valid], quality_target[valid], reduction="sum") / normalizer
        return {
            "refine_loss": self.refine_loss_weight * total_refine / normalizer,
            "quality_loss": self.quality_loss_weight * quality_loss,
        }

    def forward_train(self, feat_list, mask_list, gt_segments, gt_labels, **kwargs):
        cls, reg, start, end, reg_features, quality, points = self._dense_predictions(feat_list, mask_list, True)
        losses = self.losses(cls, reg, mask_list, points, gt_segments, gt_labels, start, end)
        losses.update(self._extra_losses(reg, start, end, reg_features, quality, mask_list, points, gt_segments, gt_labels))
        return losses

    def forward_test(self, feat_list, mask_list, **kwargs):
        cls, reg, start, end, reg_features, quality, points = self._dense_predictions(feat_list, mask_list, False)
        left, right = self.prepare_out_logits(start, end)
        refined_levels = []
        for level, reg_level in enumerate(reg):
            offsets = reg_level.permute(0, 2, 1)
            decoded_batch = []
            for batch in range(offsets.shape[0]):
                decoded_batch.append(
                    self.decode_offset(offsets[batch], left[level][batch].permute(1, 0, 2), right[level][batch].permute(1, 0, 2), False)
                )
            decoded = torch.stack(decoded_batch)  # [B,C,T,2]
            B, C, T, _ = decoded.shape
            batch_index = torch.arange(B, device=decoded.device)[:, None, None].expand(B, C, T).reshape(-1)
            time_index = torch.arange(T, device=decoded.device)[None, None, :].expand(B, C, T).reshape(-1)
            if self.inference_refine:
                refined = self._refine_selected(reg_features[level], batch_index, time_index, decoded.reshape(-1, 2))
                refined_levels.append(refined.reshape(B, C, T, 2))
            else:
                refined_levels.append(decoded)
        reg_out = torch.cat(refined_levels, dim=2)
        cls_scores = torch.cat(cls, dim=-1).permute(0, 2, 1).sigmoid()
        quality_scores = torch.cat(quality, dim=-1).permute(0, 2, 1).sigmoid()
        scores = cls_scores * quality_scores.clamp(min=1e-4).pow(self.quality_score_power)
        masks = torch.cat(mask_list, dim=1)[..., None]
        scores = scores * masks
        return torch.cat(points, dim=0), reg_out, scores
