# Joint end-to-end V-JEPA temporal adapter + frozen IV2 + Trident boundary
# refinement and localization-quality ranking. Same 211-video protocol/schedule
# as the e2e TriDet baseline.
_base_ = ["e2e_thumos_vjepa_kdbd_iv2_768x1_160_tridet.py"]

model = dict(
    rpn_head=dict(
        type="BoundaryQualityTriDetHead",
        max_refine_steps=2.0,
        refine_loss_weight=0.5,
        quality_loss_weight=0.2,
        quality_score_power=0.5,
    ),
)

work_dir = "exps/thumos/e2e_vjepa_kdbd_iv2_768x1_160_bqtridet"
