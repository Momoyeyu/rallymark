_base_ = ["../actionformer/thumos_i3d.py"]

trunc_len = 2304
data_path = "data/thumos-14/features/thumos14_6b/"
dataset = dict(
    train=dict(
        data_path=data_path,
        block_list=None,
        pipeline=[
            dict(type="LoadFeats", feat_format="pt", suffix="_spatial_feature"),
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
            dict(type="LoadFeats", feat_format="pt", suffix="_spatial_feature"),
            dict(type="ConvertToTensor", keys=["feats", "gt_segments", "gt_labels"]),
            dict(type="Rearrange", keys=["feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="feats", keys=["masks", "gt_segments", "gt_labels"]),
        ],
    ),
    test=dict(
        data_path=data_path,
        block_list=None,
        pipeline=[
            dict(type="LoadFeats", feat_format="pt", suffix="_spatial_feature"),
            dict(type="ConvertToTensor", keys=["feats"]),
            dict(type="Rearrange", keys=["feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="feats", keys=["masks"]),
        ],
    ),
)

model = dict(projection=dict(in_channels=3200))

work_dir = "exps/thumos/actionformer_iv2_6b"
