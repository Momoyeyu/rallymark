# Direct boundary evidence on the original e2e TriDet architecture.
# Same input, training schedule, losses, NMS and 211-video evaluation protocol.
_base_ = ["e2e_thumos_vjepa_kdbd_iv2_768x1_160_tridet.py"]

model = dict(
    rpn_head=dict(
        boundary_evidence=True,
        boundary_distribution_loss_weight=0.1,
    ),
)

work_dir = "exps/thumos/e2e_vjepa_kdbd_iv2_768x1_160_boundary_evidence"
