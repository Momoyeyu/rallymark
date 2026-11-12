import math
import torch
import torch.nn as nn
from torch.nn import functional as F

from ..builder import HEADS, build_loss
from .anchor_free_head import AnchorFreeHead
from ..bricks import ConvModule
from ..bricks.misc import Scale
from ..losses.iou_loss import duration_soft_iou_loss


class MultiScaleBoundaryEvidence(nn.Module):
    """Learn start/end evidence from signed changes at several temporal scales.

    The last projection is zero initialized, so an enabled head initially has
    exactly the same boundary features as the original TriDet head.
    """

    def __init__(self, channels, dilations=(1, 2, 4)):
        super().__init__()
        self.filters = nn.ModuleList(
            nn.Conv1d(3 * channels, 3 * channels, 3, padding=d, dilation=d,
                      groups=3 * channels, bias=False)
            for d in dilations
        )
        self.norm = nn.GroupNorm(1, 3 * channels * len(dilations))
        self.project = nn.Conv1d(3 * channels * len(dilations), 2 * channels, 1)
        nn.init.zeros_(self.project.weight)
        nn.init.zeros_(self.project.bias)

    def forward(self, features, mask):
        features = features * mask[:, None, :].to(features.dtype)
        previous = F.pad(features[..., :-1], (1, 0))
        following = F.pad(features[..., 1:], (0, 1))
        changes = torch.cat((features, features - previous, following - features), dim=1)
        evidence = torch.cat([conv(changes) for conv in self.filters], dim=1)
        start, end = self.project(F.relu(self.norm(evidence))).chunk(2, dim=1)
        valid = mask[:, None, :].to(start.dtype)
        return start * valid, end * valid


@HEADS.register_module()
class TriDetHead(AnchorFreeHead):
    def __init__(
        self,
        num_classes,
        in_channels,
        feat_channels,
        num_convs=3,
        cls_prior_prob=0.01,
        prior_generator=None,
        loss=None,
        loss_normalizer=100,
        loss_normalizer_momentum=0.9,
        loss_weight=1.0,
        label_smoothing=0.0,
        center_sample="radius",
        center_sample_radius=1.5,
        kernel_size=3,
        boundary_kernel_size=3,
        iou_weight_power=0.2,
        num_bins=16,
        soft_iou_weight=0.0,
        boundary_grad_scale=0.0,
        boundary_evidence=False,
        boundary_distribution_loss_weight=0.0,
    ):
        self.kernel_size = kernel_size
        self.boundary_kernel_size = boundary_kernel_size
        self.num_bins = num_bins
        self.iou_weight_power = iou_weight_power
        self.soft_iou_weight = float(soft_iou_weight)
        self.boundary_grad_scale = float(boundary_grad_scale)
        self.boundary_distribution_loss_weight = float(boundary_distribution_loss_weight)
        assert 0.0 <= self.boundary_grad_scale <= 1.0
        assert self.boundary_distribution_loss_weight >= 0.0

        super().__init__(
            num_classes,
            in_channels,
            feat_channels,
            num_convs=num_convs,
            cls_prior_prob=cls_prior_prob,
            prior_generator=prior_generator,
            loss=loss,
            loss_normalizer=loss_normalizer,
            loss_normalizer_momentum=loss_normalizer_momentum,
            loss_weight=loss_weight,
            label_smoothing=label_smoothing,
            center_sample=center_sample,
            center_sample_radius=center_sample_radius,
        )

        self._init_cls_start_convs()
        self._init_cls_end_convs()
        self.boundary_evidence = MultiScaleBoundaryEvidence(in_channels) if boundary_evidence else None

        self.iou_loss = build_loss(loss.iou_rate)

    def _init_cls_convs(self):
        """Initialize classification conv layers of the head."""
        self.cls_convs = nn.ModuleList([])
        for i in range(self.num_convs):
            self.cls_convs.append(
                ConvModule(
                    self.in_channels if i == 0 else self.feat_channels,
                    self.feat_channels,
                    kernel_size=self.kernel_size,
                    stride=1,
                    padding=self.kernel_size // 2,
                    norm_cfg=dict(type="LN"),
                    act_cfg=dict(type="relu"),
                )
            )

    def _init_reg_convs(self):
        """Initialize bbox regression conv layers of the head."""
        self.reg_convs = nn.ModuleList([])
        for i in range(self.num_convs):
            self.reg_convs.append(
                ConvModule(
                    self.in_channels if i == 0 else self.feat_channels,
                    self.feat_channels,
                    kernel_size=self.kernel_size,
                    stride=1,
                    padding=self.kernel_size // 2,
                    norm_cfg=dict(type="LN"),
                    act_cfg=dict(type="relu"),
                )
            )

    def _init_cls_start_convs(self):
        """Initialize classification conv layers of the head."""
        self.cls_start_convs = nn.ModuleList([])
        for i in range(self.num_convs):
            self.cls_start_convs.append(
                ConvModule(
                    self.in_channels if i == 0 else self.feat_channels,
                    self.feat_channels,
                    kernel_size=self.boundary_kernel_size,
                    stride=1,
                    padding=self.boundary_kernel_size // 2,
                    norm_cfg=dict(type="LN"),
                    act_cfg=dict(type="relu"),
                )
            )

    def _init_cls_end_convs(self):
        """Initialize classification conv layers of the head."""
        self.cls_end_convs = nn.ModuleList([])
        for i in range(self.num_convs):
            self.cls_end_convs.append(
                ConvModule(
                    self.in_channels if i == 0 else self.feat_channels,
                    self.feat_channels,
                    kernel_size=self.boundary_kernel_size,
                    stride=1,
                    padding=self.boundary_kernel_size // 2,
                    norm_cfg=dict(type="LN"),
                    act_cfg=dict(type="relu"),
                )
            )

    def _init_heads(self):
        """Initialize predictor layers of the head."""
        self.cls_head = nn.Conv1d(
            self.feat_channels, self.num_classes, kernel_size=self.kernel_size, padding=self.kernel_size // 2
        )
        self.reg_head = nn.Conv1d(
            self.feat_channels, 2 * (self.num_bins + 1), kernel_size=self.kernel_size, padding=self.kernel_size // 2
        )

        self.cls_start_head = nn.Conv1d(
            self.feat_channels,
            self.num_classes,
            kernel_size=self.boundary_kernel_size,
            padding=self.boundary_kernel_size // 2,
        )
        self.cls_end_head = nn.Conv1d(
            self.feat_channels,
            self.num_classes,
            kernel_size=self.boundary_kernel_size,
            padding=self.boundary_kernel_size // 2,
        )

        self.scale = nn.ModuleList([Scale() for _ in range(len(self.prior_generator.strides))])

        # use prior in model initialization to improve stability
        # this will overwrite other weight init
        if self.cls_prior_prob > 0:
            bias_value = -(math.log((1 - self.cls_prior_prob) / self.cls_prior_prob))
            torch.nn.init.constant_(self.cls_head.bias, bias_value)

    def forward_train(self, feat_list, mask_list, gt_segments, gt_labels, **kwargs):
        cls_pred = []
        reg_pred = []

        cls_start_pred = []
        cls_end_pred = []

        for l, (feat, mask) in enumerate(zip(feat_list, mask_list)):
            cls_feat = feat
            reg_feat = feat

            boundary_feat = feat.detach() + self.boundary_grad_scale * (feat - feat.detach())
            cls_start_feat = boundary_feat
            cls_end_feat = boundary_feat
            if self.boundary_evidence is not None:
                start_evidence, end_evidence = self.boundary_evidence(feat, mask)
                cls_start_feat = cls_start_feat + start_evidence
                cls_end_feat = cls_end_feat + end_evidence

            for i in range(self.num_convs):
                cls_feat, mask = self.cls_convs[i](cls_feat, mask)
                reg_feat, mask = self.reg_convs[i](reg_feat, mask)

                cls_start_feat, mask = self.cls_start_convs[i](cls_start_feat, mask)
                cls_end_feat, mask = self.cls_end_convs[i](cls_end_feat, mask)

            cls_pred.append(self.cls_head(cls_feat))
            reg_pred.append(F.relu(self.scale[l](self.reg_head(reg_feat))))
            cls_start_pred.append(self.cls_start_head(cls_start_feat))
            cls_end_pred.append(self.cls_end_head(cls_end_feat))

        points = self.prior_generator(feat_list)

        losses = self.losses(
            cls_pred,
            reg_pred,
            mask_list,
            points,
            gt_segments,
            gt_labels,
            cls_start_pred,
            cls_end_pred,
        )
        return losses

    def forward_test(self, feat_list, mask_list, **kwargs):
        cls_pred = []
        reg_pred = []
        cls_start_pred = []
        cls_end_pred = []

        for l, (feat, mask) in enumerate(zip(feat_list, mask_list)):
            cls_feat = feat
            reg_feat = feat

            cls_start_feat = feat.detach()
            cls_end_feat = feat.detach()
            if self.boundary_evidence is not None:
                start_evidence, end_evidence = self.boundary_evidence(feat, mask)
                cls_start_feat = cls_start_feat + start_evidence
                cls_end_feat = cls_end_feat + end_evidence

            for i in range(self.num_convs):
                cls_feat, mask = self.cls_convs[i](cls_feat, mask)
                reg_feat, mask = self.reg_convs[i](reg_feat, mask)

                cls_start_feat, mask = self.cls_start_convs[i](cls_start_feat, mask)
                cls_end_feat, mask = self.cls_end_convs[i](cls_end_feat, mask)

            cls_pred.append(self.cls_head(cls_feat))
            reg_pred.append(F.relu(self.scale[l](self.reg_head(reg_feat))))
            cls_start_pred.append(self.cls_start_head(cls_start_feat))
            cls_end_pred.append(self.cls_end_head(cls_end_feat))

        points = self.prior_generator(feat_list)

        # get regression offsets
        reg_pred = [x.permute(0, 2, 1) for x in reg_pred]  # list([B,T_i,2])
        left, right = self.prepare_out_logits(cls_start_pred, cls_end_pred)  # list([B C T_i, num_bins+1])
        decoded_offsets = []
        for i in range(len(left)):
            batch_offsets = []
            for j in range(reg_pred[i].shape[0]):
                batch_offsets.append(
                    self.decode_offset(
                        reg_pred[i][j],
                        left[i][j].permute(1, 0, 2),
                        right[i][j].permute(1, 0, 2),
                        False,
                    )
                )
            decoded_offsets.append(torch.stack(batch_offsets))
        reg_pred = torch.cat(decoded_offsets, dim=2)  # [B, C, T, 2]

        # get proposals and scores
        points = torch.cat(points, dim=0)  # [T,4]
        scores = torch.cat(cls_pred, dim=-1).permute(0, 2, 1).sigmoid()  # [B,T,num_classes]

        # mask out invalid
        masks = torch.cat(mask_list, dim=1)[..., None]  # [B,T,1]
        scores = scores * masks  # [B,T,num_classes]
        return points, reg_pred, scores

    def get_proposals(self, points, reg_pred):
        start = points[:, 0] - reg_pred[:, 0] * points[:, 3]
        end = points[:, 0] + reg_pred[:, 1] * points[:, 3]
        proposals = torch.stack((start, end), dim=-1)  # [N,2]
        return proposals

    def pad_and_stride(self, cls_level_i, pad_left, num_bins):
        pad = (num_bins, 0) if pad_left else (0, num_bins)
        x = (F.pad(cls_level_i, pad, mode="constant", value=0)).unsqueeze(-1)  # [B, C, T_i + bins, 1]
        x_size = list(x.size())
        x_size[-1] = num_bins + 1
        x_size[-2] = x_size[-2] - num_bins  # [B, C, T_i + bins, 1] -> [B, C, T_i, bins+1]
        x_stride = list(x.stride())
        x_stride[-2] = x_stride[-1]
        return x.as_strided(size=x_size, stride=x_stride)

    def prepare_out_logits(self, out_start, out_end):
        # out_start, out_end list([B C T_i])
        out_start_logits = []
        out_end_logits = []
        for i in range(len(out_start)):
            out_start_logits.append(self.pad_and_stride(out_start[i], True, self.num_bins).permute(0, 2, 1, 3))
            out_end_logits.append(self.pad_and_stride(out_end[i], False, self.num_bins).permute(0, 2, 1, 3))
        return out_start_logits, out_end_logits  # list([B C T_i, num_bins+1])

    def decode_offset(self, out_offsets, pred_left, pred_right, training=True):
        # decode the offset value from the network output
        # If the Trident-head is used, the predicted offset is calculated using the value from
        # center offset head (out_offsets), start boundary head (pred_left) and end boundary head (pred_right)

        # Make an adaption for train and validation, when training, the out_offsets is a list with feature outputs
        # from each FPN level. Each feature with shape [batchsize, T_level, (Num_bin+1)x2].
        # For validation, the out_offsets is a feature with shape [T_level, (Num_bin+1)x2]
        if training:
            # concat the offsets from different levels
            out_offsets = torch.cat(out_offsets, dim=1)
            out_offsets = out_offsets.view(out_offsets.shape[:2] + (2, -1))  # [B, T, 2, n_bins+1]
            pred_left = torch.cat(pred_left, dim=1)  # [B, T, C, n_bins+1]
            pred_right = torch.cat(pred_right, dim=1)  # [B, T, C, n_bins+1]

            pred_left_dis = torch.softmax(pred_left + out_offsets[:, :, :1, :], dim=-1)  # [B, T, C, n_bins+1]
            pred_right_dis = torch.softmax(pred_right + out_offsets[:, :, 1:, :], dim=-1)  # [B, T, C, n_bins+1]

        else:
            # offset from a single level
            out_offsets = out_offsets.view(out_offsets.shape[0], 2, -1)  # [T_i, 2, n_bins+1]
            pred_left_dis = torch.softmax(pred_left + out_offsets[None, :, 0, :], dim=-1)  # [C, T_i, n_bins+1]
            pred_right_dis = torch.softmax(pred_right + out_offsets[None, :, 1, :], dim=-1)

        max_range_num = pred_left_dis.shape[-1]

        left_range_idx = torch.arange(max_range_num - 1, -1, -1, device=pred_left.device, dtype=torch.float)
        right_range_idx = torch.arange(max_range_num, device=pred_right.device, dtype=torch.float)

        pred_left_dis = pred_left_dis.masked_fill(torch.isnan(pred_right_dis), 0)
        pred_right_dis = pred_right_dis.masked_fill(torch.isnan(pred_right_dis), 0)
        decoded_offset_left = torch.matmul(pred_left_dis, left_range_idx.unsqueeze(-1))
        decoded_offset_right = torch.matmul(pred_right_dis, right_range_idx.unsqueeze(-1))
        return torch.cat([decoded_offset_left, decoded_offset_right], dim=-1)

    def losses(self, cls_pred, reg_pred, mask_list, points, gt_segments, gt_labels, out_start, out_end):
        gt_cls, gt_reg = self.prepare_targets(points, gt_segments, gt_labels)

        # positive mask
        gt_cls = torch.stack(gt_cls)  # [B,sum(T),num_classes]
        gt_reg = torch.stack(gt_reg)  # [B,sum(T),2]
        gt_reg_full = gt_reg  # keep unfiltered for SoftIoU duration weights
        valid_mask = torch.cat(mask_list, dim=1)
        pos_mask = torch.logical_and((gt_cls.sum(-1) > 0), valid_mask)
        num_pos = pos_mask.sum().item()

        # maintain an EMA of foreground to stabilize the loss normalizer
        # useful for small mini-batch training
        if self.training:
            self.loss_normalizer = self.loss_normalizer_momentum * self.loss_normalizer + (
                1 - self.loss_normalizer_momentum
            ) * max(num_pos, 1)
            loss_normalizer = self.loss_normalizer
        else:
            loss_normalizer = max(num_pos, 1)

        # 1. classification loss
        cls_pred = [x.permute(0, 2, 1) for x in cls_pred]
        cls_pred = torch.cat(cls_pred, dim=1)[valid_mask]
        gt_target = gt_cls[valid_mask]

        # optional label smoothing
        gt_target *= 1 - self.label_smoothing
        gt_target += self.label_smoothing / (self.num_classes + 1)

        cls_loss = self.cls_loss(cls_pred, gt_target, reduction="none")

        # 2. regression using IoU/GIoU/DIOU loss (defined on positive samples)
        reg_pred = [x.permute(0, 2, 1) for x in reg_pred]

        # decode the offset
        out_start_logits, out_end_logits = self.prepare_out_logits(out_start, out_end)
        if self.boundary_distribution_loss_weight > 0:
            # Supervise the same fused bins that decode_offset uses at test time.
            # Center offsets are measured in units of the current FPN stride.
            offset_logits = torch.cat(reg_pred, dim=1).reshape(
                gt_cls.shape[0], -1, 2, self.num_bins + 1
            )
            start_logits = torch.cat(out_start_logits, dim=1) + offset_logits[:, :, 0:1, :]
            end_logits = torch.cat(out_end_logits, dim=1) + offset_logits[:, :, 1:2, :]
            positive_classes = gt_cls[pos_mask].bool()
            start_logits = start_logits[pos_mask][positive_classes]
            end_logits = end_logits[pos_mask][positive_classes]
            targets = gt_reg_full[pos_mask][torch.where(gt_cls[pos_mask])[0]]
            left_targets = self.num_bins - targets[:, 0]
            right_targets = targets[:, 1]
            start_loss = self._soft_bin_loss(start_logits, left_targets)
            end_loss = self._soft_bin_loss(end_logits, right_targets)
            boundary_dist_loss = 0.5 * (start_loss + end_loss)
        decoded_offsets = self.decode_offset(reg_pred, out_start_logits, out_end_logits)
        decoded_offsets = decoded_offsets[pos_mask]

        # the boundary head predicts the classification score for each categories.
        pred_offsets = decoded_offsets[gt_cls[pos_mask].bool()]
        gt_reg = gt_reg[pos_mask][torch.where(gt_cls[pos_mask])[0]]
        points = torch.cat(points, dim=0).unsqueeze(0).repeat(pos_mask.shape[0], 1, 1)
        points = points[pos_mask][torch.where(gt_cls[pos_mask])[0]]

        ## couple the classification loss with iou score
        pred_segments = self.get_proposals(points, pred_offsets)
        gt_segments = self.get_proposals(points, gt_reg)

        iou_rate = self.iou_loss(pred_segments, gt_segments, reduction="none")
        rated_mask = gt_target > self.label_smoothing / (self.num_classes + 1)
        cls_loss[rated_mask] *= (1 - iou_rate) ** self.iou_weight_power

        cls_loss = cls_loss.sum()
        cls_loss /= self.loss_normalizer

        #  regression loss
        if num_pos == 0:
            reg_loss = pred_segments.sum() * 0
        else:
            # giou loss defined on positive samples
            reg_loss = self.reg_loss(pred_segments, gt_segments, reduction="sum")
            reg_loss /= loss_normalizer

        if self.loss_weight > 0:
            loss_weight = self.loss_weight
        else:
            loss_weight = cls_loss.detach() / max(reg_loss.item(), 0.01)

        losses = {"cls_loss": cls_loss, "reg_loss": reg_loss * loss_weight}
        if self.boundary_distribution_loss_weight > 0:
            losses["boundary_dist_loss"] = (
                self.boundary_distribution_loss_weight * boundary_dist_loss
            )

        # VideoJev-style coverage SoftIoU on per-location membership (aux, default off).
        if self.soft_iou_weight > 0:
            p = cls_pred.sigmoid().amax(dim=-1)
            y = (gt_cls[valid_mask].sum(-1) > 0).float()
            dur = torch.ones_like(p)
            gt_reg_v = gt_reg_full[valid_mask]
            pos = y > 0
            if pos.any():
                dur[pos] = (gt_reg_v[pos, 0] + gt_reg_v[pos, 1]).clamp(min=1.0)
            soft = duration_soft_iou_loss(p, y, duration=dur)
            losses["soft_iou_loss"] = self.soft_iou_weight * soft

        return losses

    def _soft_bin_loss(self, logits, targets):
        """Cross entropy with linear interpolation between adjacent valid bins."""
        valid = (targets >= 0) & (targets <= self.num_bins)
        if not valid.any():
            return logits.sum() * 0
        logits = logits[valid]
        targets = targets[valid]
        lower = targets.floor().long()
        upper = targets.ceil().long()
        upper_weight = targets - lower.to(targets.dtype)
        log_probs = F.log_softmax(logits, dim=-1)
        lower_log_prob = log_probs.gather(1, lower[:, None]).squeeze(1)
        upper_log_prob = log_probs.gather(1, upper[:, None]).squeeze(1)
        return -((1 - upper_weight) * lower_log_prob + upper_weight * upper_log_prob).mean()
