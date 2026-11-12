# Local motion-guided V-JEPA alignment, zero-residual identity init.
_base_ = ["thumos_tridet_fuse_znorm_sd04_ftkdbd.py"]
model = dict(projection=dict(type="MotionAlignStreamNormTriDetProj", max_shift=2, temperature=0.35))
work_dir = "exps/thumos/tridet_fuse_znorm_sd04_ftkdbd_motion_align"
