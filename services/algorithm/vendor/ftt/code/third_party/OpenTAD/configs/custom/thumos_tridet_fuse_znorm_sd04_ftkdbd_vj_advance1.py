# One-grid V-JEPA shift control, compared with unshifted StreamNorm TriDet.
_base_ = ["thumos_tridet_fuse_znorm_sd04_ftkdbd.py"]
model = dict(projection=dict(type="TemporalShiftStreamNormTriDetProj", vj_delay=-1))
work_dir = "exps/thumos/tridet_fuse_znorm_sd04_ftkdbd_vj_advance1"
