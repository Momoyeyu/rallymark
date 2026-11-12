# TriDet on IV2-6B + VideoMAE V2-g concat, StreamNorm + stream_drop 0.4.
# Cheap feature-level check: does MAE×IV2 match the VJ×IV2 recipe?
_base_ = ["../tridet/thumos_i3d.py"]

trunc_len = 2304
data_path = "data/thumos-14/features/fuse_iv2_mae/"
dataset = dict(
    train=dict(
        data_path=data_path,
        block_list=None,
        pipeline=[
            dict(type="LoadFeats", feat_format="npy"),
            dict(type="ConvertToTensor", keys=["feats", "gt_segments", "gt_labels"]),
            dict(type="RandomTrunc", trunc_len=trunc_len, trunc_thresh=0.5, crop_ratio=[0.9, 1.0]),
            dict(type="Rearrange", keys=["feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="feats", keys=["masks", "gt_segments", "gt_labels"]),
        ],
    ),
    val=dict(
        data_path=data_path,
        block_list=None,
        pipeline=[
            dict(type="LoadFeats", feat_format="npy"),
            dict(type="ConvertToTensor", keys=["feats", "gt_segments", "gt_labels"]),
            dict(type="Rearrange", keys=["feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="feats", keys=["masks", "gt_segments", "gt_labels"]),
        ],
    ),
    test=dict(
        data_path=data_path,
        block_list=None,
        pipeline=[
            dict(type="LoadFeats", feat_format="npy"),
            dict(type="ConvertToTensor", keys=["feats"]),
            dict(type="Rearrange", keys=["feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="feats", keys=["masks"]),
        ],
    ),
)

model = dict(
    projection=dict(
        type="StreamNormTriDetProj",
        in_channels=4608,
        stream_channels=[3200, 1408],
        stats="/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/fuse_iv2_mae_stats.npz",
        stream_drop=0.4,
    )
)

work_dir = "exps/thumos/tridet_fuse_znorm_sd04_mae"
