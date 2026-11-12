_base_ = ["../actionformer/thumos_i3d.py"]

# frozen V-JEPA 2.1 ViT-g features (scripts/extract_vjepa_feats.py): one feature per 4 frames,
# feature j covers frames [4j, 4j+4), i.e. centred at ~4j+2
trunc_len = 2304
data_path = "data/thumos-14/features/vjepa21_g_256_L39/"
dataset = dict(
    train=dict(
        data_path=data_path,
        block_list=None,
        offset_frames=2,
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
        offset_frames=2,
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
        offset_frames=2,
        pipeline=[
            dict(type="LoadFeats", feat_format="npy"),
            dict(type="ConvertToTensor", keys=["feats"]),
            dict(type="Rearrange", keys=["feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="feats", keys=["masks"]),
        ],
    ),
)

model = dict(projection=dict(in_channels=1408))

work_dir = "exps/thumos/actionformer_vjepa21_g_L39"
