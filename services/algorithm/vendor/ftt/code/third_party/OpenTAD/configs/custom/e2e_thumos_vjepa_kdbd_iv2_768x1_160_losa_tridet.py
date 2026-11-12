# LoSA-style long/short gated adapters on V-JEPA (kdbd) + frozen IV2 + StreamNorm+sd0.4 + TriDet.
# Same data / schedule / fusion as e2e_thumos_vjepa_kdbd_iv2_768x1_160_tridet (76.10 baseline).
# Difference: backbone.adapters are LongShortGatedAdapter (parallel short DWConv + long window attn),
# fused onto frozen last-layer features under no_grad (losa_style=True); last 20 blocks only.
_base_ = ["e2e_thumos_vjepa_kdbd_iv2_768x1_160_tridet.py"]

model = dict(
    backbone=dict(
        backbone=dict(
            losa_style=True,
            adapter_index=list(range(20, 40)),  # ViT-g depth 40; deep stages only
            adapter_mlp_ratio=0.25,
            attn_heads=4,
            global_attn=True,  # unused when losa_style; kept for config clarity
        ),
    ),
)

work_dir = "exps/thumos/e2e_vjepa_kdbd_iv2_768x1_160_losa_tridet"
