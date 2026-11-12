_base_ = ["e2e_anet_paired_iv2_vj_tridet.py"]
root = "/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad"
ann = root + "/data/opentad/activitynet-1.3/paired_raw_iv2_20261027/pilot_32train_8val.json"
dataset = dict(train=dict(ann_file=ann), val=dict(ann_file=ann), test=dict(ann_file=ann))
evaluation = dict(ground_truth_filename=ann)
scheduler = dict(max_epoch=2, warmup_epoch=1)
workflow = dict(checkpoint_interval=1, val_eval_interval=1, val_start_epoch=0,
                end_epoch=2, logging_interval=1)
work_dir = "exps/anet/e2e_paired_iv2_vj_tridet_pilot"
