# End-to-end dual-path semantic/localization architecture. Same data, schedule,
# head supervision, seeds, and scoring as the head-only BQTriDet control.
_base_ = ["e2e_thumos_vjepa_kdbd_iv2_768x1_160_bqtridet.py"]

model = dict(
    type="DualPathBoundaryTriDet",
    boundary_hidden=128,
    rpn_head=dict(type="DualPathBoundaryQualityTriDetHead"),
)

work_dir = "exps/thumos/e2e_vjepa_kdbd_iv2_768x1_160_dualpath_bqtridet"
