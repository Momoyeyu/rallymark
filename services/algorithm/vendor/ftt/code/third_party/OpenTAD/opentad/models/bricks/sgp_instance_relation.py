"""Instance-relation conditioned local aggregation in one TriDet stem SGP block.

Modes share every parameter. V0 uses uniform local weights, V1 gates only the
short branch by action-instance probabilities, Vp gates only the dilated branch
by parent-instance probabilities, and V2 gates both. The original SGP path is
unchanged.
"""
import torch
from torch import nn
from torch.nn import functional as F

from .sgp import SGPBlock


class InstanceRelationSGPBlock(SGPBlock):
    SHORT = tuple(range(-5, 6))
    RALLY = tuple(range(-15, 16, 3))
    OFFSETS = tuple(sorted(set(SHORT + RALLY)))

    def __init__(self, *args, mode="v0", relation_dim=64, **kwargs):
        if mode not in ("v0", "v1", "vp", "v2"):
            raise ValueError(mode)
        super().__init__(*args, **kwargs)
        if self.stride != 1:
            raise ValueError("instance relations require stride=1")
        self.mode = mode
        channels = self.ln.normalized_shape[0]
        self.relation_proj = nn.Conv1d(channels, relation_dim, 1)
        self.relation_mlp = nn.Sequential(
            nn.Conv1d(3 * relation_dim + 1, relation_dim, 1),
            nn.ReLU(),
            nn.Conv1d(relation_dim, 3, 1),
        )
        self.action_value = nn.Conv1d(channels, relation_dim, 1)
        self.rally_value = nn.Conv1d(channels, relation_dim, 1)
        self.action_kernel = nn.Parameter(torch.ones(len(self.SHORT), relation_dim))
        self.rally_kernel = nn.Parameter(torch.ones(len(self.RALLY), relation_dim))
        self.action_out = nn.Conv1d(relation_dim, channels, 1)
        self.rally_out = nn.Conv1d(relation_dim, channels, 1)
        self.gamma_action = nn.Parameter(torch.zeros(()))
        self.gamma_rally = nn.Parameter(torch.zeros(()))
        # The inherited TriDet setting init_conv_vars=0 zeros psi, convw and
        # convkw. With zero gammas, their product has zero gradient forever.
        # Give psi a small nonzero weight; convw/convkw/gammas remain zero, so
        # the initial function is still identical to the original SGP block.
        nn.init.normal_(self.psi.weight, mean=0.0, std=0.02)
        nn.init.zeros_(self.psi.bias)
        self.last_relation_logits = None
        self.last_relation_offsets = self.OFFSETS

    @staticmethod
    def _shift(x, delta):
        """At t return x[t+delta], with zeros outside the sequence."""
        if delta < 0:
            return F.pad(x[..., :delta], (-delta, 0))
        if delta > 0:
            return F.pad(x[..., delta:], (0, delta))
        return x

    def _relations_and_aggregates(self, z, valid):
        batch, _, length = z.shape
        rel = self.relation_proj(z)
        av = self.action_value(z)
        rv = self.rally_value(z)
        an = torch.zeros_like(av)
        rn = torch.zeros_like(rv)
        ad = torch.zeros((batch, 1, length), device=z.device, dtype=z.dtype)
        rd = torch.zeros_like(ad)
        logits_all = []
        short_index = {delta: i for i, delta in enumerate(self.SHORT)}
        rally_index = {delta: i for i, delta in enumerate(self.RALLY)}
        for delta in self.OFFSETS:
            other = self._shift(rel, delta)
            dt = rel.new_full((batch, 1, length), float(delta) / 15.0)
            logits = self.relation_mlp(torch.cat((rel, other, rel - other, dt), 1))
            logits_all.append(logits)
            if delta not in short_index and delta not in rally_index:
                continue
            pair_valid = (valid & self._shift(valid, delta)).unsqueeze(1).to(z.dtype)
            if delta in short_index:
                if self.mode in ("v1", "v2") and delta != 0:
                    weight = logits.float().softmax(1)[:, :1].to(z.dtype) * pair_valid
                else:
                    weight = pair_valid
                an = an + self._shift(av, delta) * self.action_kernel[short_index[delta]][None, :, None] * weight
                ad = ad + weight
            if delta in rally_index:
                if self.mode in ("vp", "v2") and delta != 0:
                    weight = logits.float().softmax(1)[:, :2].sum(1, keepdim=True).to(z.dtype) * pair_valid
                else:
                    weight = pair_valid
                rn = rn + self._shift(rv, delta) * self.rally_kernel[rally_index[delta]][None, :, None] * weight
                rd = rd + weight
        self.last_relation_logits = torch.stack(logits_all, dim=-1)  # [B,3,T,offset]
        action = self.action_out(an / ad.clamp_min(1.0))
        rally = self.rally_out(rn / rd.clamp_min(1.0))
        return action, rally

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
        phi = torch.relu(self.global_fc(z.mean(dim=-1, keepdim=True)))
        action, rally = self._relations_and_aggregates(z, valid)
        out = fc * phi + (convw + convkw + self.gamma_action * action
                          + self.gamma_rally * rally) * psi + z
        out = x * out_mask + self.drop_path_out(out)
        out = out + self.drop_path_mlp(self.mlp(self.gn(out)))
        return out, valid
