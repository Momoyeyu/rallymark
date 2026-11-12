"""Online VM2-G AdaTAD FineDiving config template for OpenTAD.

Copy to configs/custom/unified_finediving_adatad_{coarse,fine}_20261111.py
after replacing LEVEL and NUM_CLASSES. Scale factor 4 makes each 192-step
detector window sample 768 native frames; 50% overlap is a 384-frame hop.
"""

_base_ = ["../adatad/thumos/e2e_thumos_videomaev2_g_768x1_160_adapter.py"]

LEVEL = "fine"
NUM_CLASSES = 29
annotation_path = f"../../data/sports_hierarchical_segments/materialized_v1/finediving/opentad_{LEVEL}.json"
class_map = f"../../data/sports_hierarchical_segments/materialized_v1/finediving/{LEVEL}_class_map.txt"
data_path = "../../data/sports_hierarchical_segments/materialized_v1/finediving/videos"

window_size = 192
scale_factor = 4
chunk_num = window_size * scale_factor // 16

train_pipeline = [
    dict(type="PrepareVideoInfo", format="mp4"),
    dict(type="mmaction.DecordInit", num_threads=4),
    dict(type="LoadFrames", num_clips=1, method="random_trunc", scale_factor=scale_factor,
         trunc_len=window_size, trunc_thresh=0.75, crop_ratio=[0.9, 1.0]),
    dict(type="mmaction.DecordDecode"),
    dict(type="mmaction.Resize", scale=(-1, 182)),
    dict(type="mmaction.RandomResizedCrop"),
    dict(type="mmaction.Resize", scale=(160, 160), keep_ratio=False),
    dict(type="mmaction.Flip", flip_ratio=0.5),
    dict(type="mmaction.FormatShape", input_format="NCTHW"),
    dict(type="ConvertToTensor", keys=["imgs", "gt_segments", "gt_labels"]),
    dict(type="Collect", inputs="imgs", keys=["masks", "gt_segments", "gt_labels"]),
]
val_pipeline = [
    dict(type="PrepareVideoInfo", format="mp4"),
    dict(type="mmaction.DecordInit", num_threads=4),
    dict(type="LoadFrames", num_clips=1, method="sliding_window", scale_factor=scale_factor),
    dict(type="mmaction.DecordDecode"),
    dict(type="mmaction.Resize", scale=(-1, 160)),
    dict(type="mmaction.CenterCrop", crop_size=160),
    dict(type="mmaction.FormatShape", input_format="NCTHW"),
    dict(type="ConvertToTensor", keys=["imgs", "gt_segments", "gt_labels"]),
    dict(type="Collect", inputs="imgs", keys=["masks", "gt_segments", "gt_labels"]),
]
eval_pipeline = [
    dict(type="PrepareVideoInfo", format="mp4"),
    dict(type="mmaction.DecordInit", num_threads=4),
    dict(type="LoadFrames", num_clips=1, method="sliding_window", scale_factor=scale_factor),
    dict(type="mmaction.DecordDecode"),
    dict(type="mmaction.Resize", scale=(-1, 160)),
    dict(type="mmaction.CenterCrop", crop_size=160),
    dict(type="mmaction.FormatShape", input_format="NCTHW"),
    dict(type="ConvertToTensor", keys=["imgs"]),
    dict(type="Collect", inputs="imgs", keys=["masks"]),
]

dataset = dict(
    train=dict(type="ThumosPaddingDataset", ann_file=annotation_path,
               subset_name="training", class_map=class_map, data_path=data_path,
               block_list=None, filter_gt=False, feature_stride=4, sample_stride=1,
               offset_frames=8, pipeline=train_pipeline),
    val=dict(type="ThumosSlidingDataset", ann_file=annotation_path,
             subset_name="validation", class_map=class_map, data_path=data_path,
             block_list=None, filter_gt=False, feature_stride=4, sample_stride=1,
             offset_frames=8, window_size=window_size, window_overlap_ratio=0.5,
             ioa_thresh=0, pipeline=val_pipeline),
    test=dict(type="ThumosSlidingDataset", ann_file=annotation_path,
              subset_name="validation", class_map=class_map, data_path=data_path,
              block_list=None, filter_gt=False, test_mode=True, feature_stride=4,
              sample_stride=1, offset_frames=8, window_size=window_size,
              window_overlap_ratio=0.5, ioa_thresh=0, pipeline=eval_pipeline),
)
evaluation = dict(type="mAP", subset="validation",
                  tiou_thresholds=[0.3, 0.4, 0.5, 0.6, 0.7],
                  ground_truth_filename=annotation_path)
model = dict(
    backbone=dict(
        backbone=dict(total_frames=window_size * scale_factor),
        custom=dict(post_processing_pipeline=[
            dict(type="Reduce", keys=["feats"], ops="b n c t h w -> b c t", reduction="mean"),
            dict(type="Rearrange", keys=["feats"], ops="(b t1) c t -> b c (t1 t)", t1=chunk_num),
            dict(type="Interpolate", keys=["feats"], size=window_size),
        ]),
    ),
    projection=dict(max_seq_len=window_size),
    rpn_head=dict(num_classes=NUM_CLASSES),
)
solver = dict(train=dict(batch_size=4, num_workers=1),
              val=dict(batch_size=4, num_workers=1),
              test=dict(batch_size=4, num_workers=1))
scheduler = dict(type="LinearWarmupCosineAnnealingLR", warmup_epoch=5, max_epoch=35)
post_processing = dict(nms=dict(max_seg_num=200, min_score=0.001))
workflow = dict(logging_interval=10, checkpoint_interval=1,
                val_loss_interval=1, val_eval_interval=1,
                val_start_epoch=0, end_epoch=15)
work_dir = f"exps/unified_five_model_20261110/finediving_adatad_{LEVEL}"
