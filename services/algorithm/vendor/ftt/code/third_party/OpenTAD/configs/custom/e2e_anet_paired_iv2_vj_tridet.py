"""Paired-video ActivityNet subset: IV2 features + trainable VJ temporal adapter + TriDet.

This is a subset protocol because only 4,447 train/351 val original videos are
both decodable and paired with the IV2 feature pack. It is not official full-ANet mAP.
"""
_base_ = ["e2e_thumos_vjepa_kdbd_iv2_768x1_160_tridet.py"]

root = "/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad"
paired = root + "/data/opentad/activitynet-1.3/paired_raw_iv2_20261027"
ann = paired + "/annotations.json"
classes = root + "/data/opentad/activitynet-1.3/annotations/category_idx.txt"
video_dir = paired + "/videos"
iv2_dir = root + "/data/opentad/activitynet-1.3/features/activitynet_6b"
stats = paired + "/iv2_train512_vj_thumos_stats.npz"
length = 192
chunks = 3
iv2_load = dict(type="LoadWindowIV2Feats", feat_dir=iv2_dir, prefix="v_",
                suffix="_spatial_pool_feature_6", feat_format="pt", alignment="duration")

train_pipeline = [
    dict(type="PrepareVideoInfo", format="mp4", prefix="v_"),
    dict(type="mmaction.DecordInit", num_threads=2),
    dict(type="LoadFrames", num_clips=1, method="resize"),
    iv2_load,
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
]
val_pipeline = [
    dict(type="PrepareVideoInfo", format="mp4", prefix="v_"),
    dict(type="mmaction.DecordInit", num_threads=2),
    dict(type="LoadFrames", num_clips=1, method="resize"),
    iv2_load,
    dict(type="mmaction.DecordDecode"),
    dict(type="mmaction.Resize", scale=(-1, 160)),
    dict(type="mmaction.CenterCrop", crop_size=160),
    dict(type="mmaction.FormatShape", input_format="NCTHW"),
    dict(type="ConvertToTensor", keys=["imgs", "gt_segments", "gt_labels", "iv2_feats"]),
    dict(type="Rearrange", keys=["iv2_feats"], ops="t c -> c t"),
    dict(type="Collect", inputs="imgs", keys=["masks", "gt_segments", "gt_labels", "iv2_feats"]),
]
test_pipeline = [
    dict(type="PrepareVideoInfo", format="mp4", prefix="v_"),
    dict(type="mmaction.DecordInit", num_threads=2),
    dict(type="LoadFrames", num_clips=1, method="resize"),
    iv2_load,
    dict(type="mmaction.DecordDecode"),
    dict(type="mmaction.Resize", scale=(-1, 160)),
    dict(type="mmaction.CenterCrop", crop_size=160),
    dict(type="mmaction.FormatShape", input_format="NCTHW"),
    dict(type="ConvertToTensor", keys=["imgs", "iv2_feats"]),
    dict(type="Rearrange", keys=["iv2_feats"], ops="t c -> c t"),
    dict(type="Collect", inputs="imgs", keys=["masks", "iv2_feats"]),
]

dataset = dict(
    _delete_=True,
    train=dict(type="AnetResizeDataset", ann_file=ann, subset_name="training", class_map=classes,
               data_path=video_dir, filter_gt=True, class_agnostic=False, resize_length=length,
               pipeline=train_pipeline),
    val=dict(type="AnetResizeDataset", ann_file=ann, subset_name="validation", class_map=classes,
             data_path=video_dir, filter_gt=True, class_agnostic=False, resize_length=length,
             pipeline=val_pipeline),
    test=dict(type="AnetResizeDataset", ann_file=ann, subset_name="validation", class_map=classes,
              data_path=video_dir, filter_gt=False, class_agnostic=False, test_mode=True,
              resize_length=length, pipeline=test_pipeline),
)
model = dict(
    backbone=dict(
        backbone=dict(total_frames=length),
        custom=dict(
            pre_processing_pipeline=[dict(type="Rearrange", keys=["frames"],
                                          ops="b n c (t1 t) h w -> (b t1) n c t h w", t1=chunks)],
            post_processing_pipeline=[
                dict(type="Reduce", keys=["feats"], ops="b n c t h w -> b c t", reduction="mean"),
                dict(type="Rearrange", keys=["feats"], ops="(b t1) c t -> b c (t1 t)", t1=chunks),
                dict(type="Interpolate", keys=["feats"], size=length),
            ],
        ),
    ),
    projection=dict(max_seq_len=length, stats=stats),
    rpn_head=dict(num_classes=200),
)
post_processing = dict(
    _delete_=True,
    nms=dict(use_soft_nms=True, sigma=0.75, max_seg_num=100,
             min_score=0.001, multiclass=True, voting_thresh=0.9),
    save_dict=True,
)
evaluation = dict(type="mAP", subset="validation",
                  tiou_thresholds=[0.5,0.55,0.6,0.65,0.7,0.75,0.8,0.85,0.9,0.95],
                  ground_truth_filename=ann)
solver = dict(train=dict(batch_size=4,num_workers=2), val=dict(batch_size=4,num_workers=2),
              test=dict(batch_size=4,num_workers=2), clip_grad_norm=0.4, ema=True, amp=True)
optimizer = dict(lr=1e-4, backbone=dict(custom=[dict(name="adapter",lr=1e-4,weight_decay=0.05)]))
scheduler = dict(max_epoch=15, warmup_epoch=2)
workflow = dict(checkpoint_interval=1, val_eval_interval=1, val_start_epoch=4, end_epoch=15,
                logging_interval=100)
work_dir = "exps/anet/e2e_paired_iv2_vj_tridet"
