_base_ = ["thumos_tridet_fuse_ftkdbd.py"]
data_path = "data/thumos-14/features/fuse_iv2_ftkdbd_anet/"
dataset = dict(train=dict(data_path=data_path), val=dict(data_path=data_path), test=dict(data_path=data_path))
model = dict(
    projection=dict(
        type="StreamNormTriDetProj",
        stream_channels=[3200, 1408],
        stats="/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/fuse_iv2_ftkdbd_anet_stats.npz",
        stream_drop=0.4,
    )
)
work_dir = "exps/thumos/tridet_fuse_znorm_sd04_ftkdbd_anet"
