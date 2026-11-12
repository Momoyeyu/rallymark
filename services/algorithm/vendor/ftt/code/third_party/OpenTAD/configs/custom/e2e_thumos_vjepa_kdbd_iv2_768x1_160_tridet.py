# Same e2e V-JEPA + frozen IV2 fusion as e2e_thumos_vjepa_kdbd_iv2_768x1_160_af, with TriDet head
# (StreamNormTriDetProj = z-norm + stream drop + TriDetProj).
_base_ = ["e2e_thumos_vjepa_kdbd_iv2_768x1_160_af.py"]

window_size = 768
iv2_stats = "/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/fuse_iv2_ftkdbd_stats.npz"

model = dict(
    type="TriDet",
    projection=dict(
        _delete_=True,
        type="StreamNormTriDetProj",
        in_channels=4608,
        stream_channels=[3200, 1408],
        stats=iv2_stats,
        stream_drop=0.4,
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
        max_seq_len=window_size,
        input_noise=0.0005,
    ),
    neck=dict(_delete_=True, type="FPNIdentity", in_channels=512, out_channels=512, num_levels=6),
    rpn_head=dict(
        _delete_=True,
        type="TriDetHead",
        num_classes=20,
        in_channels=512,
        feat_channels=512,
        num_convs=2,
        cls_prior_prob=0.01,
        prior_generator=dict(
            type="PointGenerator",
            strides=[1, 2, 4, 8, 16, 32],
            regression_range=[(0, 4), (4, 8), (8, 16), (16, 32), (32, 64), (64, 10000)],
        ),
        loss_normalizer=100,
        loss_normalizer_momentum=0.9,
        center_sample="radius",
        center_sample_radius=1.5,
        label_smoothing=0.0,
        boundary_kernel_size=3,
        iou_weight_power=0.2,
        num_bins=16,
        loss=dict(
            cls_loss=dict(type="FocalLoss"),
            reg_loss=dict(type="DIOULoss"),
            iou_rate=dict(type="GIOULoss"),
        ),
    ),
)
post_processing = dict(nms=dict(sigma=0.5, min_score=0.001))

work_dir = "exps/thumos/e2e_vjepa_kdbd_iv2_768x1_160_tridet"
