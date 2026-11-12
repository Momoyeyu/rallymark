# AdaTAD++-lite Stage A (spatial): 768 frames @ 224^2, train spatial adapter only.
# Keep IV2 StreamNorm fusion. DSW 4x80G, global batch 4.
_base_ = ["e2e_thumos_vjepa_kdbd_iv2_768x1_160_af.py"]

window_size = 768
chunk_num = window_size // 64
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
        pipeline=[
            dict(type="PrepareVideoInfo", format="mp4"),
            dict(type="mmaction.DecordInit", num_threads=4),
            dict(type="LoadFrames", num_clips=1, method="sliding_window", scale_factor=1),
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
        pipeline=[
            dict(type="PrepareVideoInfo", format="mp4"),
            dict(type="mmaction.DecordInit", num_threads=4),
            dict(type="LoadFrames", num_clips=1, method="sliding_window", scale_factor=1),
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
            total_frames=window_size,
            separable=True,
            train_parts="spatial",
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
    projection=dict(
        type="StreamNormConcatProj",
        in_channels=4608,
        stream_channels=[3200, 1408],
        stats=iv2_stats,
        stream_drop=0.4,
        input_pdrop=0.2,
    ),
)

solver = dict(
    train=dict(batch_size=4, num_workers=4),
    val=dict(batch_size=4, num_workers=4),
    test=dict(batch_size=4, num_workers=4),
)
# Stage A: fewer epochs then hand off to temporal stage (full schedule can be 30+30).
workflow = dict(checkpoint_interval=5, val_eval_interval=10, val_start_epoch=25, end_epoch=30)

work_dir = "exps/thumos/e2e_vjepa_sep_sp_768x1_224_af"
