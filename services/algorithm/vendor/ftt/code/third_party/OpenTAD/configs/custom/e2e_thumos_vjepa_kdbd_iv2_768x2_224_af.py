# Input-scale verification: same e2e V-JEPA+IV2 fusion as 768x1_160, but match AdaTAD's higher
# THUMOS setting (768 window, scale_factor=2 -> 1536 backbone frames, 224^2). Detector still sees 768.
# Compare against e2e_thumos_vjepa_kdbd_iv2_768x1_160_* (76.09) and AdaTAD-g paper 768x2_224.
_base_ = ["e2e_thumos_vjepa_kdbd_iv2_768x1_160_af.py"]

window_size = 768
scale_factor = 2
chunk_num = window_size * scale_factor // 64  # 24 chunks of 64 frames
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
                scale_factor=scale_factor,
            ),
            _iv2_load,
            dict(type="mmaction.DecordDecode"),
            dict(type="mmaction.Resize", scale=(-1, 256)),
            dict(type="mmaction.RandomResizedCrop"),
            dict(type="mmaction.Resize", scale=(224, 224), keep_ratio=False),
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
        window_size=window_size,
        pipeline=[
            dict(type="PrepareVideoInfo", format="mp4"),
            dict(type="mmaction.DecordInit", num_threads=4),
            dict(type="LoadFrames", num_clips=1, method="sliding_window", scale_factor=scale_factor),
            _iv2_load,
            dict(type="mmaction.DecordDecode"),
            dict(type="mmaction.Resize", scale=(-1, 224)),
            dict(type="mmaction.CenterCrop", crop_size=224),
            dict(type="mmaction.FormatShape", input_format="NCTHW"),
            dict(type="ConvertToTensor", keys=["imgs", "gt_segments", "gt_labels", "iv2_feats"]),
            dict(type="Rearrange", keys=["iv2_feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="imgs", keys=["masks", "gt_segments", "gt_labels", "iv2_feats"]),
        ],
    ),
    test=dict(
        window_size=window_size,
        pipeline=[
            dict(type="PrepareVideoInfo", format="mp4"),
            dict(type="mmaction.DecordInit", num_threads=4),
            dict(type="LoadFrames", num_clips=1, method="sliding_window", scale_factor=scale_factor),
            _iv2_load,
            dict(type="mmaction.DecordDecode"),
            dict(type="mmaction.Resize", scale=(-1, 224)),
            dict(type="mmaction.CenterCrop", crop_size=224),
            dict(type="mmaction.FormatShape", input_format="NCTHW"),
            dict(type="ConvertToTensor", keys=["imgs", "iv2_feats"]),
            dict(type="Rearrange", keys=["iv2_feats"], ops="t c -> c t"),
            dict(type="Collect", inputs="imgs", keys=["masks", "iv2_feats"]),
        ],
    ),
)

model = dict(
    backbone=dict(
        backbone=dict(
            img_size=224,
            total_frames=window_size * scale_factor,
        ),
        custom=dict(
            pre_processing_pipeline=[
                dict(type="Rearrange", keys=["frames"], ops="b n c (t1 t) h w -> (b t1) n c t h w", t1=chunk_num),
            ],
            post_processing_pipeline=[
                dict(type="Reduce", keys=["feats"], ops="b n c t h w -> b c t", reduction="mean"),
                dict(type="Rearrange", keys=["feats"], ops="(b t1) c t -> b c (t1 t)", t1=chunk_num),
                dict(type="Interpolate", keys=["feats"], size=window_size),
            ],
        ),
    ),
)

# Global batch must be divisible by world size (4). Peak ~46 GiB/GPU at train bs=1, so val/test keep 4.
solver = dict(
    train=dict(batch_size=4, num_workers=4),
    val=dict(batch_size=4, num_workers=4),
    test=dict(batch_size=4, num_workers=4),
)

work_dir = "exps/thumos/e2e_vjepa_kdbd_iv2_768x2_224_af"
