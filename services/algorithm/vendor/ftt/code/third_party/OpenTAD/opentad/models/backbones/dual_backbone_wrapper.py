"""Two online video backbones for the THUMOS VideoMAEv2-G + V-JEPA pilot.

Each branch keeps its own preprocessing and temporal chunking. The returned
feature order is VideoMAE, V-JEPA. Both branches receive gradients through
their internal adapters; their pretrained weights remain frozen by the
respective backbone implementations.
"""

import torch
import torch.nn as nn

from .backbone_wrapper import BackboneWrapper


class DualBackboneWrapper(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        assert len(cfg.branches) == 2, "Expected exactly two video branches"
        self.branches = nn.ModuleList([BackboneWrapper(branch) for branch in cfg.branches])
        for branch in self.branches:
            for name, param in branch.model.backbone.named_parameters():
                if "adapter" not in name:
                    param.requires_grad_(False)
            assert any(param.requires_grad for param in branch.model.backbone.parameters()), (
                "No trainable adapter parameters in " + type(branch.model.backbone).__name__
            )
        # OpenTAD's optimizer checks this flag before collecting adapter params.
        self.freeze_backbone = False

    def forward(self, frames, masks=None):
        outputs = [branch(frames, masks) for branch in self.branches]
        target_length = outputs[0].shape[-1]
        assert all(out.ndim == 3 and out.shape[-1] == target_length for out in outputs), [
            tuple(out.shape) for out in outputs
        ]
        return torch.cat(outputs, dim=1)


class FrozenDualBackboneWrapper(DualBackboneWrapper):
    """Two fixed video branches for training one adapter after feature fusion."""

    def __init__(self, cfg):
        super().__init__(cfg)
        for branch in self.branches:
            branch.freeze_backbone = True
            for param in branch.parameters():
                param.requires_grad_(False)
        self.freeze_backbone = True

    def train(self, mode=True):
        super().train(mode)
        for branch in self.branches:
            branch.eval()
        return self
