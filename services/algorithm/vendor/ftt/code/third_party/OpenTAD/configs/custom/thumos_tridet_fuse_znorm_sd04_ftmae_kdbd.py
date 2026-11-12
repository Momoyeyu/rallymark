# TriDet on IV2-6B + FT VideoMAE V2-g (kdbd), StreamNorm + stream_drop 0.4.
_base_ = ["thumos_tridet_fuse_znorm_sd04_mae.py"]

data_path = "data/thumos-14/features/fuse_iv2_ftmae_kdbd/"
dataset = dict(
    train=dict(data_path=data_path),
    val=dict(data_path=data_path),
    test=dict(data_path=data_path),
)
model = dict(
    projection=dict(
        stats="/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/fuse_iv2_ftmae_kdbd_stats.npz",
    )
)
work_dir = "exps/thumos/tridet_fuse_znorm_sd04_ftmae_kdbd"
