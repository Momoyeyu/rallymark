# TriDet on IV2-6B + V-JEPA kdbd concat, standardised + stream drop 0.4; compare thumos_af_fuse_znorm_sd04_ftkdbd
_base_ = ["thumos_tridet_fuse_ftkdbd.py"]

model = dict(
    projection=dict(
        type="StreamNormTriDetProj",
        stream_channels=[3200, 1408],
        stats="/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/fuse_iv2_ftkdbd_stats.npz",
        stream_drop=0.4,
    )
)

work_dir = "exps/thumos/tridet_fuse_znorm_sd04_ftkdbd"
