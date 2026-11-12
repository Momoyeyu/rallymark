_base_ = ["../actionformer/thumos_i3d.py"]

annotation_path = "../../data/sports_hierarchical_segments/materialized_v1/finediving/opentad_fine.json"
class_map = "../../data/sports_hierarchical_segments/materialized_v1/finediving/fine_class_map.txt"
data_path = "../../data/finediving/feature_extraction_v1/features/videomaev2_g_16_4/"
block_list = data_path + "missing_files.txt"

dataset = dict(
    train=dict(ann_file=annotation_path, class_map=class_map, data_path=data_path,
               block_list=block_list, subset_name="training", feature_stride=4,
               sample_stride=1, offset_frames=8),
    val=dict(ann_file=annotation_path, class_map=class_map, data_path=data_path,
             block_list=block_list, subset_name="validation", feature_stride=4,
             sample_stride=1, offset_frames=8),
    test=dict(ann_file=annotation_path, class_map=class_map, data_path=data_path,
              block_list=block_list, subset_name="validation", feature_stride=4,
              sample_stride=1, offset_frames=8),
)
evaluation = dict(type="mAP", subset="validation",
                  tiou_thresholds=[0.3, 0.4, 0.5, 0.6, 0.7],
                  ground_truth_filename=annotation_path)
model = dict(projection=dict(in_channels=1408),
             rpn_head=dict(num_classes=29))
solver = dict(train=dict(batch_size=4, num_workers=1),
              val=dict(batch_size=4, num_workers=1),
              test=dict(batch_size=4, num_workers=1),
              clip_grad_norm=1, ema=True)
scheduler = dict(type="LinearWarmupCosineAnnealingLR", warmup_epoch=5, max_epoch=35)
post_processing = dict(nms=dict(use_soft_nms=True, sigma=0.5,
                                max_seg_num=200, min_score=0.001,
                                multiclass=True, voting_thresh=0.7),
                       save_dict=False)
workflow = dict(logging_interval=10, checkpoint_interval=1,
                val_loss_interval=1, val_eval_interval=1, val_start_epoch=0,
                end_epoch=15)
work_dir = "exps/unified_five_model_20261110/finediving_actionformer_fine"
