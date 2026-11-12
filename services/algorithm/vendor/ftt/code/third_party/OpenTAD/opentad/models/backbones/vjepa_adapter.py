"""Frozen V-JEPA 2.1 ViT-g with trainable temporal adapters for end-to-end TAD (AdaTAD-style).

The window (e.g. 768 frames sampled every 4 native frames) is split into chunks of `chunk_frames` (64, the V-JEPA
pre-training clip length, vs 16 for VideoMAE) by the OpenTAD pre-processing pipeline, so the backbone sees
[B * n_chunks, 3, chunk_frames, H, W]. Every adapted block is followed by a residual adapter whose temporal mixing
spans the whole window, i.e. it crosses chunk boundaries:
  - TIA branch (AdaTAD): depth-wise temporal conv per spatial position;
  - optional global branch (after AdaTAD++, which replaces the temporal conv by a transformer): multi-head
    self-attention over the spatially pooled tokens of the whole window, broadcast back to every position.
The up projection is zero-initialised, so training starts from exactly the initialisation checkpoint's features.
"""
import math
import os
import sys

import torch
import torch.nn as nn
import torch.utils.checkpoint as cp
from mmengine.registry import MODELS

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 5))
for _p in (f"{_ROOT}/env_pack/pylib_opentad", f"{_ROOT}/third_party/vjepa2"):  # timm for vjepa2 on the py3.11 env
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TemporalAdapter(nn.Module):
    def __init__(self, dim, temporal_size, mlp_ratio=0.25, kernel_size=3, global_attn=True, num_heads=8):
        super().__init__()
        hidden = int(dim * mlp_ratio)
        self.temporal_size = temporal_size
        self.down_proj = nn.Linear(dim, hidden)
        self.act = nn.GELU()
        self.dwconv = nn.Conv1d(hidden, hidden, kernel_size, padding=kernel_size // 2, groups=hidden)
        self.conv = nn.Conv1d(hidden, hidden, 1)
        nn.init.normal_(self.dwconv.weight, std=math.sqrt(2.0 / kernel_size))
        nn.init.zeros_(self.dwconv.bias)
        nn.init.normal_(self.conv.weight, std=math.sqrt(2.0 / hidden))
        nn.init.zeros_(self.conv.bias)
        self.global_attn = global_attn
        if global_attn:
            self.attn_norm = nn.LayerNorm(hidden)
            self.pos = nn.Parameter(torch.zeros(1, temporal_size, hidden))
            nn.init.trunc_normal_(self.pos, std=0.02)
            self.attn = nn.MultiheadAttention(hidden, num_heads, batch_first=True)
        self.up_proj = nn.Linear(hidden, dim)
        nn.init.trunc_normal_(self.down_proj.weight, std=0.02)
        nn.init.zeros_(self.down_proj.bias)
        nn.init.zeros_(self.up_proj.weight)
        nn.init.zeros_(self.up_proj.bias)
        self.gamma = nn.Parameter(torch.ones(1))

    def forward(self, x, h, w):
        z = self.act(self.down_proj(x))  # [B*chunks, t*h*w, c]
        n, l, c = z.shape
        a = z.reshape(-1, self.temporal_size, h, w, c)  # chunks of one sample are contiguous -> whole window
        y = a.permute(0, 2, 3, 4, 1).flatten(0, 2)  # [b*h*w, c, T]
        y = self.conv(self.dwconv(y))
        y = y.unflatten(0, (-1, h, w)).permute(0, 4, 1, 2, 3)  # [b, T, h, w, c]
        if self.global_attn:
            # fp32 attention: MultiheadAttention under fp16 autocast is a common NaN source
            g = self.attn_norm(a.mean((2, 3)).float()) + self.pos.float()
            with torch.cuda.amp.autocast(enabled=False):
                g = self.attn(g, g, g, need_weights=False)[0]
            y = y + g.to(dtype=y.dtype)[:, :, None, None, :]
        z = z + y.reshape(n, l, c)
        return x + self.gamma * self.up_proj(z)


class SeparableAdapter(nn.Module):
    """AdaTAD++-lite: spatial (plain bottleneck) and temporal (TIA + optional window attn) with separate ups.

    train_parts: 'spatial' | 'temporal' | 'all' — freeze the other branch via requires_grad.
    Shared down_proj stays trainable in both stages (small; needed for both paths).
    """

    def __init__(self, dim, temporal_size, mlp_ratio=0.25, kernel_size=3, global_attn=True, num_heads=8,
                 train_parts="all"):
        super().__init__()
        hidden = int(dim * mlp_ratio)
        self.temporal_size = temporal_size
        self.train_parts = train_parts
        self.down_proj = nn.Linear(dim, hidden)
        self.act = nn.GELU()
        # spatial branch
        self.up_spatial = nn.Linear(hidden, dim)
        self.gamma_spatial = nn.Parameter(torch.ones(1))
        # temporal branch
        self.dwconv = nn.Conv1d(hidden, hidden, kernel_size, padding=kernel_size // 2, groups=hidden)
        self.conv = nn.Conv1d(hidden, hidden, 1)
        nn.init.normal_(self.dwconv.weight, std=math.sqrt(2.0 / kernel_size))
        nn.init.zeros_(self.dwconv.bias)
        nn.init.normal_(self.conv.weight, std=math.sqrt(2.0 / hidden))
        nn.init.zeros_(self.conv.bias)
        self.global_attn = global_attn
        if global_attn:
            self.attn_norm = nn.LayerNorm(hidden)
            self.pos = nn.Parameter(torch.zeros(1, temporal_size, hidden))
            nn.init.trunc_normal_(self.pos, std=0.02)
            self.attn = nn.MultiheadAttention(hidden, num_heads, batch_first=True)
        self.up_temporal = nn.Linear(hidden, dim)
        self.gamma_temporal = nn.Parameter(torch.ones(1))
        nn.init.trunc_normal_(self.down_proj.weight, std=0.02)
        nn.init.zeros_(self.down_proj.bias)
        nn.init.zeros_(self.up_spatial.weight)
        nn.init.zeros_(self.up_spatial.bias)
        nn.init.zeros_(self.up_temporal.weight)
        nn.init.zeros_(self.up_temporal.bias)
        self.apply_train_parts(train_parts)

    def apply_train_parts(self, train_parts):
        self.train_parts = train_parts
        spat = ("up_spatial", "gamma_spatial")
        temp = ("dwconv", "conv", "up_temporal", "gamma_temporal")
        if self.global_attn:
            temp = temp + ("attn_norm", "pos", "attn")
        # shared down always trainable
        for n, p in self.named_parameters():
            if n.startswith("down_proj"):
                p.requires_grad = True
            elif any(n == k or n.startswith(k + ".") for k in spat):
                p.requires_grad = train_parts in ("spatial", "all")
            elif any(n == k or n.startswith(k + ".") for k in temp):
                p.requires_grad = train_parts in ("temporal", "all")
            else:
                p.requires_grad = train_parts == "all"

    def forward(self, x, h, w):
        # Always run both branches; freezing is via requires_grad only (stage-B needs spatial features).
        z = self.act(self.down_proj(x))
        n, l, c = z.shape
        out = x + self.gamma_spatial * self.up_spatial(z)
        a = z.reshape(-1, self.temporal_size, h, w, c)
        y = a.permute(0, 2, 3, 4, 1).flatten(0, 2)
        y = self.conv(self.dwconv(y))
        y = y.unflatten(0, (-1, h, w)).permute(0, 4, 1, 2, 3)
        if self.global_attn:
            g = self.attn_norm(a.mean((2, 3)).float()) + self.pos.float()
            with torch.cuda.amp.autocast(enabled=False):
                g = self.attn(g, g, g, need_weights=False)[0]
            y = y + g.to(dtype=y.dtype)[:, :, None, None, :]
        zt = z + y.reshape(n, l, c)
        return out + self.gamma_temporal * self.up_temporal(zt)


class LongShortGatedAdapter(nn.Module):
    """LoSA-inspired parallel short/long adapters that emit a gated residual (not in-block rewrite).

    Short: depth-wise temporal conv (local). Long: full-window self-attention.
    Learnable gates start at 0 so the fused trunk begins as the frozen last-layer features.
    """

    def __init__(self, dim, temporal_size, mlp_ratio=0.25, kernel_size=3, num_heads=4):
        super().__init__()
        hidden = int(dim * mlp_ratio)
        self.temporal_size = temporal_size
        self.down = nn.Linear(dim, hidden)
        self.act = nn.GELU()
        # short-range
        self.dwconv = nn.Conv1d(hidden, hidden, kernel_size, padding=kernel_size // 2, groups=hidden)
        self.conv = nn.Conv1d(hidden, hidden, 1)
        nn.init.normal_(self.dwconv.weight, std=math.sqrt(2.0 / kernel_size))
        nn.init.zeros_(self.dwconv.bias)
        nn.init.normal_(self.conv.weight, std=math.sqrt(2.0 / hidden))
        nn.init.zeros_(self.conv.bias)
        self.up_sh = nn.Linear(hidden, dim)
        self.gate_sh = nn.Parameter(torch.zeros(1))
        # long-range
        self.attn_norm = nn.LayerNorm(hidden)
        self.pos = nn.Parameter(torch.zeros(1, temporal_size, hidden))
        nn.init.trunc_normal_(self.pos, std=0.02)
        self.attn = nn.MultiheadAttention(hidden, num_heads, batch_first=True)
        self.up_lo = nn.Linear(hidden, dim)
        self.gate_lo = nn.Parameter(torch.zeros(1))
        nn.init.trunc_normal_(self.down.weight, std=0.02)
        nn.init.zeros_(self.down.bias)
        nn.init.zeros_(self.up_sh.weight)
        nn.init.zeros_(self.up_sh.bias)
        nn.init.zeros_(self.up_lo.weight)
        nn.init.zeros_(self.up_lo.bias)

    def forward(self, x, h, w):
        """x: [B*chunks, t*h*w, C] → gated residual same shape (0 at init)."""
        z = self.act(self.down(x))
        n, l, c = z.shape
        a = z.reshape(-1, self.temporal_size, h, w, c)
        # short: per-location temporal conv over the whole window
        y = a.permute(0, 2, 3, 4, 1).flatten(0, 2)  # [b*h*w, c, T]
        y = self.conv(self.dwconv(y))
        y = y.unflatten(0, (-1, h, w)).permute(0, 4, 1, 2, 3)  # [b, T, h, w, c]
        short = self.up_sh(y.reshape(n, l, c))
        # long: window self-attn on spatially pooled tokens, broadcast
        g = self.attn_norm(a.mean((2, 3)).float()) + self.pos.float()
        with torch.cuda.amp.autocast(enabled=False):
            g = self.attn(g, g, g, need_weights=False)[0]
        long = self.up_lo(g.to(dtype=z.dtype)[:, :, None, None, :].expand(-1, -1, h, w, -1).reshape(n, l, c))
        return self.gate_sh * short + self.gate_lo * long


@MODELS.register_module()
class VJEPAAdapter(nn.Module):
    """Returns [B * chunks, C, chunk_frames / 2, H / 16, W / 16] after the final norm (as in feature extraction)."""

    def __init__(
        self,
        ckpt,
        img_size=160,
        chunk_frames=64,
        total_frames=768,
        adapter_index=None,  # default: every block
        adapter_mlp_ratio=0.25,
        global_attn=True,
        attn_heads=8,
        drop_path_rate=0.1,
        with_cp=True,
        separable=False,  # AdaTAD++-lite split spatial/temporal adapters
        train_parts="all",  # 'spatial' | 'temporal' | 'all' (only if separable)
        losa_style=False,  # LoSA-inspired: parallel long/short, fuse onto frozen last-layer feats
    ):
        super().__init__()
        from app.vjepa_2_1.models import vision_transformer as vit

        self.enc = vit.vit_giant_xformers(
            patch_size=16, img_size=(img_size, img_size), num_frames=chunk_frames, tubelet_size=2, use_sdpa=True,
            uniform_power=False, use_rope=True, img_temporal_dim_size=1, interpolate_rope=True,
            drop_path_rate=drop_path_rate)
        sd = torch.load(ckpt, map_location="cpu")["target_encoder"]
        sd = {k.replace("module.", "").replace("backbone.", ""): v for k, v in sd.items()}
        self.enc.load_state_dict(sd, strict=True)
        for p in self.enc.parameters():
            p.requires_grad = False
        depth, dim = len(self.enc.blocks), self.enc.embed_dim
        self.adapter_index = list(range(depth)) if adapter_index is None else list(adapter_index)
        self.separable = separable
        self.train_parts = train_parts
        self.losa_style = losa_style
        if losa_style:
            assert not separable, "losa_style and separable are mutually exclusive"
            self.adapters = nn.ModuleDict({
                str(i): LongShortGatedAdapter(
                    dim, total_frames // 2, mlp_ratio=adapter_mlp_ratio, num_heads=min(attn_heads, 4),
                )
                for i in self.adapter_index
            })
        else:
            ad_cls = SeparableAdapter if separable else TemporalAdapter
            kw = dict(mlp_ratio=adapter_mlp_ratio, global_attn=global_attn, num_heads=attn_heads)
            if separable:
                kw["train_parts"] = train_parts
            self.adapters = nn.ModuleDict({
                str(i): ad_cls(dim, total_frames // 2, **kw) for i in self.adapter_index})
        self.with_cp = with_cp and not losa_style  # LoSA path runs backbone under no_grad
        n_enc = sum(p.numel() for p in self.enc.parameters())
        n_ad = sum(p.numel() for p in self.adapters.parameters())
        n_tr = sum(p.numel() for p in self.adapters.parameters() if p.requires_grad)
        print(f"V-JEPA params {n_enc / 1e6:.0f}M (frozen), adapter params {n_ad / 1e6:.1f}M "
              f"({100 * n_ad / n_enc:.1f}%), trainable {n_tr / 1e6:.1f}M "
              f"[separable={separable} train_parts={train_parts} losa_style={losa_style}]")
    def set_train_parts(self, train_parts):
        """Switch which adapter branch is trainable (separable mode only). Call after loading a ckpt."""
        assert self.separable, "set_train_parts requires separable=True"
        self.train_parts = train_parts
        for ad in self.adapters.values():
            ad.apply_train_parts(train_parts)
        n_tr = sum(p.numel() for p in self.adapters.parameters() if p.requires_grad)
        print(f"[VJEPAAdapter] train_parts={train_parts}, trainable adapter params {n_tr / 1e6:.1f}M")

    def train(self, mode=True):
        # Keep the frozen encoder in eval so DropPath stays off (drop_path_rate=0.1 would otherwise
        # randomly zero residual branches; the DSW ablation hit Loss=nan from epoch 9).
        super().train(mode)
        self.enc.eval()
        return self

    def forward(self, x):
        enc = self.enc
        b, _, t, hh, ww = x.shape
        T, h, w = t // enc.tubelet_size, hh // enc.patch_size, ww // enc.patch_size
        kw = dict(mask=None, T=T, H_patches=h, W_patches=w, return_attn=False, mode="video")
        if self.losa_style:
            # Backbone fully detached (LoSA memory path); only adapters + gated fusion train.
            mid = {}
            with torch.no_grad():
                z = enc.patch_embed(x)
                if enc.modality_embedding:
                    z = z + enc.video_mod_embed.repeat(b, 1, 1)
                for i, blk in enumerate(enc.blocks):
                    z = blk(z, **kw)[0]
                    if str(i) in self.adapters:
                        mid[i] = z
                z = enc.norms_block[-1](z)
            out = z
            for i, feat in mid.items():
                out = out + self.adapters[str(i)](feat, h, w)
            return out.reshape(b, T, h, w, -1).permute(0, 4, 1, 2, 3)

        with torch.no_grad():
            z = enc.patch_embed(x)
            if enc.modality_embedding:
                z = z + enc.video_mod_embed.repeat(b, 1, 1)
        for i, blk in enumerate(enc.blocks):
            ad = self.adapters[str(i)] if str(i) in self.adapters else None

            def run(z, blk=blk, ad=ad):
                # Encoder weights are frozen (requires_grad=False) but stay in the graph so gradients
                # flow from later adapters back through earlier ones.
                z = blk(z, **kw)[0]
                return ad(z, h, w) if ad is not None else z

            if self.with_cp and self.training:
                z = cp.checkpoint(run, z, use_reentrant=False)
            else:
                z = run(z)
        z = enc.norms_block[-1](z)
        return z.reshape(b, T, h, w, -1).permute(0, 4, 1, 2, 3)
