# standardised concat + stream drop 0.4; compare thumos_af_fuse_concat_sd04
_base_ = ["thumos_af_fuse_znorm.py"]

model = dict(projection=dict(stream_drop=0.4))

work_dir = "exps/thumos/af_fuse_znorm_sd04"
