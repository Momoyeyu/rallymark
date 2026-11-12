# AdaTAD++-lite inference: 1536 @ 224 with both spatial+temporal adapters (train_parts=all, no train).
_base_ = ["e2e_thumos_vjepa_sep_te_768x2_160_af.py"]

window_size = 768
scale_factor = 2
chunk_num = window_size * scale_factor // 64
iv2_dir = "/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/thumos14_6b"
_iv2_load = dict(type="LoadWindowIV2Feats", feat_dir=iv2_dir, suffix="_spatial_feature", feat_format="pt", center_offset=8)

dataset = dict(
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
            separable=True,
            train_parts="all",
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

work_dir = "exps/thumos/e2e_vjepa_sep_infer_768x2_224_af"
