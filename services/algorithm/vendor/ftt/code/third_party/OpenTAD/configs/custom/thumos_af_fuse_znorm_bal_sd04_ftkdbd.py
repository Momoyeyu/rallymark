# standardised concat, both streams scaled to equal total variance, + stream drop 0.4, on IV2 + V-JEPA kdbd
_base_ = ["thumos_af_fuse_znorm_sd04_ftkdbd.py"]

model = dict(projection=dict(balance=True))

work_dir = "exps/thumos/af_fuse_znorm_bal_sd04_ftkdbd"
