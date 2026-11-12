# Cross-attn stream fusion (bidirectional) + StreamNorm + stream_drop 0.4 + TriDet.
# Same data as thumos_tridet_fuse_znorm_sd04_ftkdbd (76.10); only the projection changes.
# Cross-attn out-proj is zero-init → starts as two independent projected streams.
_base_ = ["thumos_tridet_fuse_ftkdbd.py"]

iv2_stats = "/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/fuse_iv2_ftkdbd_stats.npz"

model = dict(
    projection=dict(
        _delete_=True,
        type="CrossAttnStreamTriDetProj",
        in_channels=1024,  # 2 * fuse_channels after cross-attn (raw input still 4608)
        stream_channels=[3200, 1408],
        stats=iv2_stats,
        stream_drop=0.4,
        fuse_channels=512,
        num_heads=8,
        num_layers=1,
        out_channels=512,
        sgp_mlp_dim=768,
        arch=(2, 2, 5),
        downsample_type="max",
        sgp_win_size=[1, 1, 1, 1, 1, 1],
        k=5,
        init_conv_vars=0,
        conv_cfg=dict(kernel_size=3),
        norm_cfg=dict(type="LN"),
        path_pdrop=0.1,
        use_abs_pe=False,
        max_seq_len=2304,
        input_noise=0.0005,
    ),
)

work_dir = "exps/thumos/tridet_fuse_xattn_sd04_ftkdbd"
