# Sparse native-frame boundary zoom on the unchanged e2e TriDet backbone/head.
# Up to 8 class proposals per window, two boundaries, five 64x64 native frames.
# Joint objective: original TriDet classification/regression + bounded zoom loss.
_base_ = ["e2e_thumos_vjepa_kdbd_iv2_768x1_160_tridet.py"]

model = dict(
    type="SparseBoundaryZoomTriDet",
    zoom_topk=8,
    zoom_train_gt=8,
    zoom_loss_weight=0.15,
)
work_dir = "exps/thumos/e2e_vjepa_kdbd_iv2_768x1_160_sparse_zoom"
