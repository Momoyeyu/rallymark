"""ActivityNet-v1.3 IV2-6B single-stream, internally classified TriDet baseline.

Class-aware detection avoids unavailable external video classifiers. The input is
OpenTAD's pre-extracted 16-frame/8-stride InternVideo2-6B feature pack.
"""
_base_ = ["../tridet/anet_tsp.py"]

ann = "data/activitynet-1.3/annotations/activity_net.v1-3.min.json"
classes = "data/activitynet-1.3/annotations/category_idx.txt"
feats = "data/activitynet-1.3/features/activitynet_6b/"
missing = "data/activitynet-1.3/features/activitynet_6b/missing_feature_ids.txt"
length = 192

train_pipeline = [
    dict(type="LoadFeats", feat_format="pt", prefix="v_", suffix="_spatial_pool_feature_6"),
    dict(type="ConvertToTensor", keys=["feats", "gt_segments", "gt_labels"]),
    dict(type="ResizeFeat", tool="torchvision_align"),
    dict(type="RandomTrunc", trunc_len=length, trunc_thresh=0.5, crop_ratio=[0.9, 1.0]),
    dict(type="Rearrange", keys=["feats"], ops="t c -> c t"),
    dict(type="Collect", inputs="feats", keys=["masks", "gt_segments", "gt_labels"]),
]
val_pipeline = [
    dict(type="LoadFeats", feat_format="pt", prefix="v_", suffix="_spatial_pool_feature_6"),
    dict(type="ConvertToTensor", keys=["feats", "gt_segments", "gt_labels"]),
    dict(type="ResizeFeat", tool="torchvision_align"),
    dict(type="Rearrange", keys=["feats"], ops="t c -> c t"),
    dict(type="Collect", inputs="feats", keys=["masks", "gt_segments", "gt_labels"]),
]
test_pipeline = [
    dict(type="LoadFeats", feat_format="pt", prefix="v_", suffix="_spatial_pool_feature_6"),
    dict(type="ConvertToTensor", keys=["feats"]),
    dict(type="ResizeFeat", tool="torchvision_align"),
    dict(type="Rearrange", keys=["feats"], ops="t c -> c t"),
    dict(type="Collect", inputs="feats", keys=["masks"]),
]

dataset = dict(
    _delete_=True,
    train=dict(type="AnetResizeDataset", ann_file=ann, subset_name="training", block_list=missing,
               class_map=classes, data_path=feats, filter_gt=True, class_agnostic=False,
               resize_length=length, pipeline=train_pipeline),
    val=dict(type="AnetResizeDataset", ann_file=ann, subset_name="validation", block_list=None,
             class_map=classes, data_path=feats, filter_gt=True, class_agnostic=False,
             resize_length=length, pipeline=val_pipeline),
    test=dict(type="AnetResizeDataset", ann_file=ann, subset_name="validation", block_list=None,
              class_map=classes, data_path=feats, filter_gt=False, class_agnostic=False,
              test_mode=True, resize_length=length, pipeline=test_pipeline),
)
model = dict(
    projection=dict(in_channels=3200, max_seq_len=length),
    rpn_head=dict(num_classes=200),
)
post_processing = dict(
    _delete_=True,
    nms=dict(use_soft_nms=True, sigma=0.75, max_seg_num=100,
             min_score=0.001, multiclass=True, voting_thresh=0.9),
    save_dict=True,
)
solver = dict(
    train=dict(batch_size=8, num_workers=4),
    val=dict(batch_size=8, num_workers=4),
    test=dict(batch_size=8, num_workers=4),
    clip_grad_norm=0.4,
    ema=True,
)
workflow = dict(logging_interval=100, checkpoint_interval=1, val_loss_interval=1,
                val_eval_interval=1, val_start_epoch=7)
work_dir = "exps/anet/tridet_iv2_6b_cls200"
