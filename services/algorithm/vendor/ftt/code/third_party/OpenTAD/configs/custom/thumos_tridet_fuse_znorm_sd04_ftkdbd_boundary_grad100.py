# Full boundary-head gradient into shared TriDet projection.
_base_ = ["thumos_tridet_fuse_znorm_sd04_ftkdbd.py"]
model = dict(rpn_head=dict(boundary_grad_scale=1.0))
work_dir = "exps/thumos/tridet_fuse_znorm_sd04_ftkdbd_boundary_grad100"
