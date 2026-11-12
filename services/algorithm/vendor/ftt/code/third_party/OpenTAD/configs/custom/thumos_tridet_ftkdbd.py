# TriDet on V-JEPA kdbd features only (fair single-stream vs IV2-only and dual fuse).
# Same recipe as thumos_tridet_iv2_6b / thumos_af_ftkdbd (offset_frames=4, npy, 1408-d).
_base_ = ["../tridet/thumos_i3d.py"]

trunc_len = 2304
data_path = "data/thumos-14/features/vjepa21_g_ftkdbd_s4_L39/"
dataset = dict(
    train=dict(
        data_path=data_path,
        block_list=None,
        offset_frames=4,
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
        offset_frames=4,
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
        offset_frames=4,
        pipeline=[
            dict(type="LoadFeats", feat_format="npy"),
            dict(type="ConvertToTensor", keys=["feats"]),
            dict(type="Rearrange", keys=["feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="feats", keys=["masks"]),
        ],
    ),
)

model = dict(projection=dict(in_channels=1408))

work_dir = "exps/thumos/tridet_ftkdbd"
