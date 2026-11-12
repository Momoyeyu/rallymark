import torch
import torch.nn as nn
from ..builder import LOSSES
from ..utils.iou_tools import compute_diou_torch, compute_giou_torch, compute_iou_torch


@LOSSES.register_module()
class DIOULoss(nn.Module):
    def __init__(self):
        super(DIOULoss, self).__init__()

    def forward(
        self,
        input_bboxes: torch.Tensor,
        target_bboxes: torch.Tensor,
        reduction: str = "none",
        eps: float = 1e-8,
    ) -> torch.Tensor:
        loss = 1 - torch.diag(compute_diou_torch(target_bboxes, input_bboxes))

        if reduction == "mean":
            loss = loss.mean() if loss.numel() > 0 else 0.0 * loss.sum()
        elif reduction == "sum":
            loss = loss.sum()

        return loss


@LOSSES.register_module()
class GIOULoss(nn.Module):
    def __init__(self):
        super(GIOULoss, self).__init__()

    def forward(
        self,
        input_bboxes: torch.Tensor,
        target_bboxes: torch.Tensor,
        reduction: str = "none",
        eps: float = 1e-8,
    ) -> torch.Tensor:
        loss = 1 - torch.diag(compute_giou_torch(target_bboxes, input_bboxes))

        if reduction == "mean":
            loss = loss.mean() if loss.numel() > 0 else 0.0 * loss.sum()
        elif reduction == "sum":
            loss = loss.sum()
        return loss


@LOSSES.register_module()
class SoftIoULoss(nn.Module):
    """Pairwise 1D Soft-IoU regression loss: 1 - IoU(pred, gt) on the diagonal.

    Drop-in alternative to DIOULoss / GIOULoss for TriDet ``reg_loss`` / ``iou_rate``.
    """

    def __init__(self):
        super(SoftIoULoss, self).__init__()

    def forward(
        self,
        input_bboxes: torch.Tensor,
        target_bboxes: torch.Tensor,
        reduction: str = "none",
        eps: float = 1e-8,
    ) -> torch.Tensor:
        loss = 1 - torch.diag(compute_iou_torch(target_bboxes, input_bboxes))

        if reduction == "mean":
            loss = loss.mean() if loss.numel() > 0 else 0.0 * loss.sum()
        elif reduction == "sum":
            loss = loss.sum()
        return loss


def duration_soft_iou_loss(pred_prob, gt_mask, duration=None, eps=1e-6):
    """VideoJev-style duration-weighted SoftIoU on temporal membership scores.

    L = 1 - sum(d p y) / sum(d [y + p (1-y)]). Returns 0 when no positive y
    (same omit rule as VideoJev). ``pred_prob`` / ``gt_mask`` / ``duration`` are 1-D.
    """
    p = pred_prob.float().clamp(0.0, 1.0)
    y = gt_mask.float()
    if y.sum() <= 0:
        return p.sum() * 0.0
    d = torch.ones_like(p) if duration is None else duration.float().clamp(min=eps)
    inter = (d * p * y).sum()
    union = (d * (y + p * (1.0 - y))).sum().clamp(min=eps)
    return 1.0 - inter / union
