import numpy as np
import torch
import torch.nn as nn

from ..bricks import ConvModule
from ..builder import PROJECTIONS
from .actionformer_proj import Conv1DTransformerProj
from .tridet_proj import TriDetProj


def drop_streams(x, stream_channels, p):
    """Zero one whole stream (chosen uniformly) of each sample with probability p."""
    b, n = x.shape[0], len(stream_channels)
    drop = torch.rand(b, device=x.device) < p
    which = torch.randint(n, (b,), device=x.device)
    keep = torch.ones(b, n, device=x.device, dtype=x.dtype)
    keep[drop, which[drop]] = 0
    keep = torch.repeat_interleave(keep, torch.tensor(stream_channels, device=x.device), dim=1)
    return x * keep.unsqueeze(-1)


def stream_norm_buffers(module, stats, stream_channels, in_channels, balance):
    """Register feat_mean / feat_scale for per-channel standardisation (see StreamNormConcatProj)."""
    st = np.load(stats)
    mean = torch.from_numpy(st["mean"]).float()
    std = torch.from_numpy(st["std"]).float()
    assert len(mean) == in_channels
    scale = 1.0 / std
    if balance:
        n = len(stream_channels)
        w = torch.cat([torch.full((c,), (in_channels / (n * c)) ** 0.5) for c in stream_channels])
        scale = scale * w
    module.register_buffer("feat_mean", mean.view(1, -1, 1), persistent=False)
    module.register_buffer("feat_scale", scale.view(1, -1, 1), persistent=False)


def stream_norm(module, x, mask):
    return (x - module.feat_mean.to(x.dtype)) * module.feat_scale.to(x.dtype) * mask.unsqueeze(1).to(x.dtype)


@PROJECTIONS.register_module()
class StreamDropConcatProj(Conv1DTransformerProj):
    """ActionFormer projection over channel-concatenated streams (`stream_channels`), where during training each
    sample has one whole stream zeroed with probability `stream_drop` (streams chosen uniformly)."""

    def __init__(self, stream_channels, stream_drop=0.2, **kwargs):
        super().__init__(**kwargs)
        assert sum(stream_channels) == self.in_channels
        self.stream_channels = list(stream_channels)
        self.stream_drop = stream_drop

    def forward(self, x, mask):
        if self.training and self.stream_drop > 0:
            x = drop_streams(x, self.stream_channels, self.stream_drop)
        return super().forward(x, mask)


@PROJECTIONS.register_module()
class StreamNormConcatProj(StreamDropConcatProj):
    """StreamDropConcatProj on per-channel standardised input, using fixed training-subset statistics (`stats`:
    npz with mean / std over all channels, see scripts/fuse_stats.py). Raw IV2 / V-JEPA channels differ ~25x in
    total variance, so without this the first conv is dominated by one stream. With `balance`, every stream is
    further scaled to the same total variance (C_total / n_streams) regardless of its width."""

    def __init__(self, stream_channels, stats, balance=False, stream_drop=0.0, **kwargs):
        super().__init__(stream_channels, stream_drop=stream_drop, **kwargs)
        stream_norm_buffers(self, stats, self.stream_channels, self.in_channels, balance)

    def forward(self, x, mask):
        return super().forward(stream_norm(self, x, mask), mask)


@PROJECTIONS.register_module()
class StreamNormTriDetProj(TriDetProj):
    """TriDet projection with the StreamNormConcatProj input treatment (standardise, then whole-stream drop)."""

    def __init__(self, stream_channels, stats, balance=False, stream_drop=0.0, **kwargs):
        super().__init__(**kwargs)
        assert sum(stream_channels) == self.in_channels
        self.stream_channels = list(stream_channels)
        self.stream_drop = stream_drop
        stream_norm_buffers(self, stats, self.stream_channels, self.in_channels, balance)

    def forward(self, x, mask):
        x = stream_norm(self, x, mask)
        if self.training and self.stream_drop > 0:
            x = drop_streams(x, self.stream_channels, self.stream_drop)
        return super().forward(x, mask)


@PROJECTIONS.register_module()
class GatedFusionProj(Conv1DTransformerProj):
    """ActionFormer projection over a two-stream input whose channels are split by `stream_channels`.

    Each stream is mapped to `fuse_channels` by a 1x1 conv + LN. A temporal conv over both streams predicts a
    per-time, per-channel sigmoid gate g, and the fused input g * a + (1 - g) * b goes through the usual
    ActionFormer embedding / transformer stack. With `stream_drop` > 0, during training each sample keeps only one
    stream (gate forced to 1 or 0) with that probability, so the detector cannot learn to ignore either stream.
    """

    def __init__(self, stream_channels, fuse_channels=512, gate_kernel=3, stream_drop=0.0, in_channels=None, **kwargs):
        super().__init__(in_channels=fuse_channels, **kwargs)  # in_channels inherited from base configs is unused
        assert len(stream_channels) == 2
        self.stream_channels = list(stream_channels)
        self.streams = nn.ModuleList(
            [ConvModule(c, fuse_channels, kernel_size=1, norm_cfg=dict(type="LN")) for c in stream_channels]
        )
        self.gate = nn.Conv1d(2 * fuse_channels, fuse_channels, kernel_size=gate_kernel, padding=gate_kernel // 2)
        nn.init.zeros_(self.gate.weight)  # start from an even mix
        nn.init.zeros_(self.gate.bias)
        self.stream_drop = stream_drop

    def forward(self, x, mask):
        a, b = [m(s, mask)[0] for m, s in zip(self.streams, x.split(self.stream_channels, dim=1))]
        g = torch.sigmoid(self.gate(torch.cat([a, b], dim=1)))
        if self.training and self.stream_drop > 0:
            r = torch.rand(x.shape[0], 1, 1, device=x.device)
            g = torch.where(r < self.stream_drop / 2, torch.ones_like(g), g)
            g = torch.where((r >= self.stream_drop / 2) & (r < self.stream_drop), torch.zeros_like(g), g)
        x = (g * a + (1 - g) * b) * mask.unsqueeze(1).to(a.dtype)
        return super().forward(x, mask)


class _CrossStreamBlock(nn.Module):
    """One bidirectional cross-attn block: A←B and B←A, residual + LN. Out-proj zero-init → identity at start."""

    def __init__(self, dim, num_heads=8):
        super().__init__()
        self.norm_a = nn.LayerNorm(dim)
        self.norm_b = nn.LayerNorm(dim)
        self.attn_ab = nn.MultiheadAttention(dim, num_heads, batch_first=True)  # A queries B
        self.attn_ba = nn.MultiheadAttention(dim, num_heads, batch_first=True)  # B queries A
        nn.init.zeros_(self.attn_ab.out_proj.weight)
        nn.init.zeros_(self.attn_ab.out_proj.bias)
        nn.init.zeros_(self.attn_ba.out_proj.weight)
        nn.init.zeros_(self.attn_ba.out_proj.bias)

    def forward(self, a, b, key_padding_mask):
        # a,b: [B, T, D]; key_padding_mask True = ignore
        aa = self.norm_a(a.float())
        bb = self.norm_b(b.float())
        with torch.cuda.amp.autocast(enabled=False):
            da, _ = self.attn_ab(aa, bb, bb, key_padding_mask=key_padding_mask, need_weights=False)
            db, _ = self.attn_ba(bb, aa, aa, key_padding_mask=key_padding_mask, need_weights=False)
        return a + da.to(dtype=a.dtype), b + db.to(dtype=b.dtype)


@PROJECTIONS.register_module()
class CrossAttnStreamTriDetProj(TriDetProj):
    """TriDet projection with StreamNorm + optional stream drop, then bidirectional cross-attn fusion.

    Raw input stays channel-concat [IV2 | VJ] (e.g. 4608). Each stream is 1x1-projected to ``fuse_channels``,
    exchanged via ``num_layers`` of bidirectional temporal cross-attention (keeps both streams, unlike gated
    "pick one"), then concatenated to ``2 * fuse_channels`` for the TriDet stem. Attention out-proj is zero-init
    so training starts as two independent projected streams (no interaction).
    """

    def __init__(
        self,
        stream_channels,
        stats,
        fuse_channels=512,
        num_heads=8,
        num_layers=1,
        balance=False,
        stream_drop=0.0,
        in_channels=None,  # ignored; TriDet sees 2 * fuse_channels
        **kwargs,
    ):
        assert len(stream_channels) == 2
        super().__init__(in_channels=2 * fuse_channels, **kwargs)
        self.stream_channels = list(stream_channels)
        self.stream_drop = stream_drop
        self.raw_in_channels = sum(self.stream_channels)
        stream_norm_buffers(self, stats, self.stream_channels, self.raw_in_channels, balance)
        self.streams = nn.ModuleList(
            [ConvModule(c, fuse_channels, kernel_size=1, norm_cfg=dict(type="LN")) for c in self.stream_channels]
        )
        self.blocks = nn.ModuleList([_CrossStreamBlock(fuse_channels, num_heads) for _ in range(num_layers)])

    def forward(self, x, mask):
        assert x.shape[1] == self.raw_in_channels, (x.shape, self.raw_in_channels)
        x = stream_norm(self, x, mask)
        if self.training and self.stream_drop > 0:
            x = drop_streams(x, self.stream_channels, self.stream_drop)
        a, b = [m(s, mask)[0] for m, s in zip(self.streams, x.split(self.stream_channels, dim=1))]
        # [B, C, T] -> [B, T, C]
        a, b = a.transpose(1, 2), b.transpose(1, 2)
        kpm = ~mask.bool() if mask.dtype == torch.bool else mask < 0.5
        for blk in self.blocks:
            a, b = blk(a, b, kpm)
        x = torch.cat([a.transpose(1, 2), b.transpose(1, 2)], dim=1)  # [B, 2C, T]
        x = x * mask.unsqueeze(1).to(x.dtype)
        return super().forward(x, mask)


@PROJECTIONS.register_module()
class TemporalShiftStreamNormTriDetProj(StreamNormTriDetProj):
    """Shift only the V-JEPA stream by one feature step as an alignment control.

    vj_delay=1 sets output[t] = VJ[t-1]; vj_delay=-1 sets output[t] = VJ[t+1].
    Edge values repeat the nearest valid feature, and the sequence mask is unchanged.
    """

    def __init__(self, vj_delay=1, **kwargs):
        super().__init__(**kwargs)
        assert len(self.stream_channels) == 2
        assert vj_delay in (-1, 1)
        self.vj_delay = vj_delay

    def forward(self, x, mask):
        a, b = x.split(self.stream_channels, dim=1)
        if self.vj_delay == 1:
            b = torch.cat((b[..., :1], b[..., :-1]), dim=-1)
        else:
            b = torch.cat((b[..., 1:], b[..., -1:]), dim=-1)
        return super().forward(torch.cat((a, b), dim=1), mask)

def _edge_shift(x, offset):
    """Return y[t] = x[t + offset], repeating endpoint features."""
    if offset < 0:
        n = -offset
        return torch.cat([x[..., :1].expand(*x.shape[:-1], n), x[..., :-n]], dim=-1)
    if offset > 0:
        return torch.cat([x[..., offset:], x[..., -1:].expand(*x.shape[:-1], offset)], dim=-1)
    return x


@PROJECTIONS.register_module()
class MotionAlignStreamNormTriDetProj(StreamNormTriDetProj):
    """Local motion-guided temporal alignment, retaining both streams and TriDet stem.

    Motion change magnitudes from standardized streams score V-JEPA shifts in a
    small window around each IV2 time step. A learnable zero-initialized residual
    controls how much aligned V-JEPA replaces the original, so initialization is
    exactly the established concat baseline.
    """

    def __init__(self, max_shift=2, temperature=0.35, **kwargs):
        super().__init__(**kwargs)
        assert len(self.stream_channels) == 2
        assert max_shift >= 1
        self.max_shift = max_shift
        self.temperature = temperature
        self.offsets = list(range(-max_shift, max_shift + 1))
        self.offset_bias = nn.Parameter(torch.zeros(len(self.offsets)))
        self.strength_bias = nn.Parameter(torch.tensor(0.0))

    def forward(self, x, mask):
        a, b = stream_norm(self, x, mask).split(self.stream_channels, dim=1)
        # Standardized per-channel RMS change; invariant to stream width.
        da = torch.cat([torch.zeros_like(a[:, :1, :1]),
                        (a[..., 1:] - a[..., :-1]).square().mean(1, keepdim=True).sqrt()], dim=-1)
        db = torch.cat([torch.zeros_like(b[:, :1, :1]),
                        (b[..., 1:] - b[..., :-1]).square().mean(1, keepdim=True).sqrt()], dim=-1)
        valid = mask.unsqueeze(1).to(da.dtype)
        for d in (da, db):
            mu = (d * valid).sum(-1, keepdim=True) / valid.sum(-1, keepdim=True).clamp_min(1)
            d.sub_(mu)
            sd = ((d.square() * valid).sum(-1, keepdim=True) /
                  valid.sum(-1, keepdim=True).clamp_min(1)).sqrt().clamp_min(1e-4)
            d.div_(sd)
        scores = torch.cat(
            [-(da - _edge_shift(db, j)).abs() / self.temperature +
             self.offset_bias[i] for i, j in enumerate(self.offsets)], dim=1)
        weights = scores.softmax(dim=1)
        b_raw = x[:, self.stream_channels[0]:]
        aligned = sum(weights[:, i:i+1] * _edge_shift(b_raw, j)
                      for i, j in enumerate(self.offsets))
        b_raw = b_raw + self.strength_bias.tanh() * (aligned - b_raw)
        fused = torch.cat([x[:, :self.stream_channels[0]], b_raw], dim=1)
        return super().forward(fused, mask)
