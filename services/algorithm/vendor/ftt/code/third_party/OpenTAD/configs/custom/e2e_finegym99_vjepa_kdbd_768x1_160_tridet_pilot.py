"""FineGym99 event-internal element TAD, source-disjoint pilot.

V-JEPA adapter + TriDet branch of the current model. The frozen IV2 stream
requires FineGym-specific features and is intentionally absent in this pilot.
"""

_base_ = ["e2e_thumos_vjepa_kdbd_768x1_160_tridet.py"]

finegym_root = "/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/finegym"
annotation_path = finegym_root + "/gym99_tad_source_disjoint_v1/annotations.json"
class_map = finegym_root + "/gym99_tad_source_disjoint_v1/class_map.txt"
data_path = finegym_root + "/event_videos"

dataset = dict(
    train=dict(ann_file=annotation_path, subset_name="training", class_map=class_map, data_path=data_path),
    val=dict(ann_file=annotation_path, subset_name="validation", class_map=class_map, data_path=data_path),
    test=dict(ann_file=annotation_path, subset_name="validation", class_map=class_map, data_path=data_path),
)

model = dict(rpn_head=dict(num_classes=99))
evaluation = dict(
    type="mAP",
    subset="validation",
    tiou_thresholds=[0.1, 0.2, 0.3, 0.4, 0.5],
    ground_truth_filename=annotation_path,
)

workflow = dict(checkpoint_interval=2, val_eval_interval=5, val_start_epoch=4, end_epoch=20)
scheduler = dict(max_epoch=20, warmup_epoch=2)
work_dir = "exps/finegym/e2e_finegym99_vjepa_kdbd_768x1_160_tridet_pilot"
