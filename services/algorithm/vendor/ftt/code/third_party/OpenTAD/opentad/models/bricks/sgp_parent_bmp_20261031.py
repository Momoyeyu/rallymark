"""Matched FTT M/P parent-conditioned SGP branch.

M and P share parameters, predicted center mass, and auxiliary supervision.
Only the allocation of non-center mass differs.
"""
import torch
from torch import nn
from torch.nn import functional as F

from .sgp import SGPBlock


class ParentBMPBlock(SGPBlock):
    OFFSETS = tuple(range(-15, 16, 3))

    def __init__(self, *args, mode="m", relation_dim=64, **kwargs):
        if mode not in ("m", "p"):
            raise ValueError(mode)
        super().__init__(*args, **kwargs)
        if self.stride != 1:
            raise ValueError("parent branch requires stride=1")
        self.mode = mode
        channels = self.ln.normalized_shape[0]
        self.relation_proj = nn.Conv1d(channels, relation_dim, 1)
        self.relation_mlp = nn.Sequential(
            nn.Conv1d(3 * relation_dim + 1, relation_dim, 1),
            nn.ReLU(),
            nn.Conv1d(relation_dim, 1, 1),
        )
        self.value = nn.Conv1d(channels, relation_dim, 1)
        self.kernel = nn.Parameter(torch.ones(len(self.OFFSETS), relation_dim))
        self.value_out = nn.Conv1d(relation_dim, channels, 1)
        self.gamma = nn.Parameter(torch.zeros(()))
        self.last_relation_logits = None
        self.last_rho = None

    @staticmethod
    def _shift(x, delta):
        if delta < 0:
            return F.pad(x[..., :delta], (-delta, 0))
        if delta > 0:
            return F.pad(x[..., delta:], (0, delta))
        return x

    def _aggregate(self, z, valid):
        batch, _, length = z.shape
        h = self.relation_proj(z)
        value = self.value(z)
        logits = []
        probs = []
        shifted = []
        pair_masks = []
        for i, delta in enumerate(self.OFFSETS):
            if delta == 0:
                continue
            other = self._shift(h, delta)
            offset = h.new_full((batch, 1, length), delta / 15.0)
            logit = self.relation_mlp(torch.cat((h, other, h - other, offset), 1))
            pair_valid = (valid & self._shift(valid, delta)).unsqueeze(1)
            logits.append(logit)
            probs.append(logit.float().sigmoid().to(z.dtype) * pair_valid)
            shifted.append(self._shift(value, delta) * self.kernel[i][None, :, None])
            pair_masks.append(pair_valid)
        score = torch.stack(probs, -1)  # [B,1,T,K]
        count = torch.stack(pair_masks, -1).sum(-1).clamp_min(1)
        score_sum = score.sum(-1)
        rho = 1.0 / (1.0 + score_sum)
        # Identical center mass for M and P. In M, every valid non-center
        # neighbor receives the same remaining mass; in P, it is proportional
        # to predicted same-parent probability.
        if self.mode == "m":
            weights = score_sum.unsqueeze(-1) * torch.stack(pair_masks, -1) / count.unsqueeze(-1)
        else:
            weights = score
        aggregate = value
        for i, part in enumerate(shifted):
            aggregate = aggregate + part * weights[..., i]
        aggregate = self.value_out(aggregate * rho)
        self.last_relation_logits = torch.cat(logits, 1).transpose(1, 2)  # [B,T,K]
        self.last_rho = rho.detach()
        return aggregate

    def forward(self, x, mask):
        _, _, length = x.shape
        x = self.downsample(x)
        out_mask = F.interpolate(mask.unsqueeze(1).to(x.dtype), size=length, mode="nearest").detach()
        valid = out_mask.squeeze(1).bool()
        z = self.ln(x.permute(0, 2, 1)).permute(0, 2, 1)
        psi = self.psi(z)
        fc = self.fc(z)
        convw = self.convw(z)
        convkw = self.convkw(z)
        phi = torch.relu(self.global_fc(z.mean(-1, keepdim=True)))
        parent = self._aggregate(z, valid)
        out = fc * phi + (convw + convkw + self.gamma * parent) * psi + z
        out = x * out_mask + self.drop_path_out(out)
        out = out + self.drop_path_mlp(self.mlp(self.gn(out)))
        return out, valid
