# End-to-end V-JEPA (kdbd, frozen + temporal adapters) channel-concatenated with frozen InternVideo2-6B
# features, then StreamNormConcatProj (train-subset z-norm + stream drop 0.4) + ActionFormer.
# IV2 alignment matches scripts/build_fused_feats.py (IV2 centre at native frame 4j+8).
_base_ = ["e2e_thumos_vjepa_kdbd_768x1_160_af.py"]

window_size = 768
iv2_dir = "/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/thumos14_6b"
iv2_stats = "/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/fuse_iv2_ftkdbd_stats.npz"

_iv2_load = dict(type="LoadWindowIV2Feats", feat_dir=iv2_dir, suffix="_spatial_feature", feat_format="pt", center_offset=8)

dataset = dict(
    train=dict(
        pipeline=[
            dict(type="PrepareVideoInfo", format="mp4"),
            dict(type="mmaction.DecordInit", num_threads=4),
            dict(
                type="LoadFrames",
                num_clips=1,
                method="random_trunc",
                trunc_len=window_size,
                trunc_thresh=0.75,
                crop_ratio=[0.9, 1.0],
                scale_factor=1,
            ),
            _iv2_load,
            dict(type="mmaction.DecordDecode"),
            dict(type="mmaction.Resize", scale=(-1, 182)),
            dict(type="mmaction.RandomResizedCrop"),
            dict(type="mmaction.Resize", scale=(160, 160), keep_ratio=False),
            dict(type="mmaction.Flip", flip_ratio=0.5),
            dict(type="mmaction.ImgAug", transforms="default"),
            dict(type="mmaction.ColorJitter"),
            dict(type="mmaction.FormatShape", input_format="NCTHW"),
            dict(type="ConvertToTensor", keys=["imgs", "gt_segments", "gt_labels", "iv2_feats"]),
            dict(type="Rearrange", keys=["iv2_feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="imgs", keys=["masks", "gt_segments", "gt_labels", "iv2_feats"]),
        ],
    ),
    val=dict(
        pipeline=[
            dict(type="PrepareVideoInfo", format="mp4"),
            dict(type="mmaction.DecordInit", num_threads=4),
            dict(type="LoadFrames", num_clips=1, method="sliding_window", scale_factor=1),
            _iv2_load,
            dict(type="mmaction.DecordDecode"),
            dict(type="mmaction.Resize", scale=(-1, 160)),
            dict(type="mmaction.CenterCrop", crop_size=160),
            dict(type="mmaction.FormatShape", input_format="NCTHW"),
            dict(type="ConvertToTensor", keys=["imgs", "gt_segments", "gt_labels", "iv2_feats"]),
            dict(type="Rearrange", keys=["iv2_feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="imgs", keys=["masks", "gt_segments", "gt_labels", "iv2_feats"]),
        ],
    ),
    test=dict(
        pipeline=[
            dict(type="PrepareVideoInfo", format="mp4"),
            dict(type="mmaction.DecordInit", num_threads=4),
            dict(type="LoadFrames", num_clips=1, method="sliding_window", scale_factor=1),
            _iv2_load,
            dict(type="mmaction.DecordDecode"),
            dict(type="mmaction.Resize", scale=(-1, 160)),
            dict(type="mmaction.CenterCrop", crop_size=160),
            dict(type="mmaction.FormatShape", input_format="NCTHW"),
            dict(type="ConvertToTensor", keys=["imgs", "iv2_feats"]),
            dict(type="Rearrange", keys=["iv2_feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="imgs", keys=["masks", "iv2_feats"]),
        ],
    ),
)

model = dict(
    projection=dict(
        type="StreamNormConcatProj",
        in_channels=4608,
        stream_channels=[3200, 1408],
        stats=iv2_stats,
        stream_drop=0.4,
        input_pdrop=0.2,
    ),
)

work_dir = "exps/thumos/e2e_vjepa_kdbd_iv2_768x1_160_af"
