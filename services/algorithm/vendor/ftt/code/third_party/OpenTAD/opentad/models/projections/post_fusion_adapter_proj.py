"""One trainable temporal adapter after concatenating two fixed video features."""
import torch
import torch.nn as nn
import torch.nn.functional as F
from ..builder import PROJECTIONS
from .tridet_proj import TriDetProj


@PROJECTIONS.register_module()
class PostFusionTemporalAdapterTriDetProj(TriDetProj):
    def __init__(self, adapter_hidden=2048, adapter_kernel=3, **kwargs):
        super().__init__(**kwargs)
        channels = self.in_channels
        self.adapter_norm = nn.LayerNorm(channels)
        self.adapter_down = nn.Conv1d(channels, adapter_hidden, 1)
        self.adapter_temporal = nn.Conv1d(adapter_hidden, adapter_hidden, adapter_kernel,
                                          padding=adapter_kernel // 2, groups=adapter_hidden)
        self.adapter_up = nn.Conv1d(adapter_hidden, channels, 1)
        nn.init.zeros_(self.adapter_up.weight)
        nn.init.zeros_(self.adapter_up.bias)

    def forward(self, x, mask):
        valid = mask.unsqueeze(1).to(x.dtype)
        y = self.adapter_norm(x.transpose(1, 2)).transpose(1, 2)
        y = F.gelu(self.adapter_down(y))
        y = F.gelu(self.adapter_temporal(y))
        y = self.adapter_up(y)
        return super().forward((x + y) * valid, mask)
