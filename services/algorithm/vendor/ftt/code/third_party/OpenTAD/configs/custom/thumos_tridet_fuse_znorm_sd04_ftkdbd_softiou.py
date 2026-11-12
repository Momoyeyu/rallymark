# Frozen IV2+kdbd fuse TriDet (znorm+sd04) + VideoJev-style duration SoftIoU aux.
# Weight 0.5 keeps SoftIoU on the same order as TriDet cls/reg (~0.1–0.5); VideoJev's 2.0
# assumes BCE-scale losses and would dominate here (~2.0 vs ~0.2).
# Compare thumos_tridet_fuse_znorm_sd04_ftkdbd (76.10 avg).
_base_ = ["thumos_tridet_fuse_znorm_sd04_ftkdbd.py"]

model = dict(
    rpn_head=dict(soft_iou_weight=0.5),
)

work_dir = "exps/thumos/tridet_fuse_znorm_sd04_ftkdbd_softiou"
