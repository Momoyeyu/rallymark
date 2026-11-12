# standardised concat, both streams scaled to equal total variance, + stream drop 0.4
_base_ = ["thumos_af_fuse_znorm.py"]

model = dict(projection=dict(balance=True, stream_drop=0.4))

work_dir = "exps/thumos/af_fuse_znorm_bal_sd04"
