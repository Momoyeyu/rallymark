"""Parent-continuity local context for the last non-downsampling TriDet SGP stem.

The original SGP path is copied exactly. A zero-initialized scalar adds a
position-dependent local context, so initialization reproduces SGPBlock.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
from .sgp import SGPBlock


class ParentContinuitySGPBlock(SGPBlock):
    def __init__(self, *args, context_window=31, continuity_hidden=64, **kwargs):
        if context_window <= 1 or context_window % 2 != 1:
            raise ValueError('context_window must be odd and > 1')
        super().__init__(*args, **kwargs)
        if self.stride != 1:
            raise ValueError('continuity context is only for non-downsampling stem')
        self.context_window = context_window
        channels = self.ln.normalized_shape[0]
        self.continuity_head = nn.Sequential(
            nn.Conv1d(channels, continuity_hidden, 1), nn.ReLU(),
            nn.Conv1d(continuity_hidden, continuity_hidden, 3, padding=1), nn.ReLU(),
            nn.Conv1d(continuity_hidden, 1, 1))
        self.local_fc = nn.Conv1d(channels, channels, 1, groups=channels)
        nn.init.zeros_(self.local_fc.bias)
        self.local_scale = nn.Parameter(torch.zeros(()))
        self.last_q_logits = None

    def _local_context(self, features, valid, q):
        batch, channels, length = features.shape
        v = valid.to(features.dtype)
        numer = features * v[:, None, :]
        denom = v.clone()
        left_path = torch.ones_like(q)
        right_path = torch.ones_like(q)
        for distance in range(1, min(self.context_window // 2, length - 1) + 1):
            # q[t] joins positions t-1 and t. Products never cross the padded edge.
            left_edge = F.pad(q[:, :length - distance + 1], (distance - 1, 0))
            right_edge = F.pad(q[:, distance:], (0, distance))
            left_path = left_path * left_edge
            right_path = right_path * right_edge
            left_valid = F.pad(v[:, :length - distance], (distance, 0))
            right_valid = F.pad(v[:, distance:], (0, distance))
            lw = left_path * left_valid
            rw = right_path * right_valid
            numer = numer + F.pad(features[:, :, :length - distance], (distance, 0)) * lw[:, None]
            numer = numer + F.pad(features[:, :, distance:], (0, distance)) * rw[:, None]
            denom = denom + lw + rw
        return numer / denom.clamp_min(1e-6)[:, None, :]

    def forward(self, x, mask):
        batch, channels, length = x.shape
        x = self.downsample(x)
        out_mask = F.interpolate(mask.unsqueeze(1).to(x.dtype),
                                 size=torch.div(length, self.stride, rounding_mode='trunc'),
                                 mode='nearest').detach()
        valid = out_mask.squeeze(1).bool()
        out = self.ln(x.permute(0, 2, 1)).permute(0, 2, 1)
        psi = self.psi(out)
        fc = self.fc(out)
        convw = self.convw(out)
        convkw = self.convkw(out)
        phi = torch.relu(self.global_fc(out.mean(dim=-1, keepdim=True)))
        logits = self.continuity_head(out).squeeze(1)
        self.last_q_logits = logits
        q = logits.float().sigmoid()
        local = self._local_context(out.float(), valid, q).to(out.dtype)
        local_phi = torch.relu(self.local_fc(local))
        out = fc * phi + self.local_scale * out * local_phi + (convw + convkw) * psi + out
        out = x * out_mask + self.drop_path_out(out)
        out = out + self.drop_path_mlp(self.mlp(self.gn(out)))
        return out, valid
