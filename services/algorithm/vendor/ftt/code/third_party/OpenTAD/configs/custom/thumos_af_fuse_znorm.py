# concat + per-channel standardisation with training-subset stats (StreamNormConcatProj); compare thumos_af_fuse_concat
_base_ = ["thumos_af_fuse_concat.py"]

model = dict(
    projection=dict(
        type="StreamNormConcatProj",
        stream_channels=[3200, 1408],
        stats="/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/fuse_iv2_vjft_stats.npz",
        stream_drop=0.0,
        input_pdrop=0.2,
    )
)

work_dir = "exps/thumos/af_fuse_znorm"
