# Same fuse TriDet baseline, but replace DIoU regression with Soft-IoU (1 - IoU).
# Orthogonal SoftIoU interpretation vs coverage aux in *_softiou.py.
_base_ = ["thumos_tridet_fuse_znorm_sd04_ftkdbd.py"]

model = dict(
    rpn_head=dict(
        loss=dict(
            cls_loss=dict(type="FocalLoss"),
            reg_loss=dict(type="SoftIoULoss"),
            iou_rate=dict(type="GIOULoss"),
        ),
    ),
)

work_dir = "exps/thumos/tridet_fuse_znorm_sd04_ftkdbd_softiou_reg"
