# Stage B on DLC 8 GPU: temporal-only @ 1536x160, global batch 8.
_base_ = ["e2e_thumos_vjepa_sep_te_768x2_160_af.py"]

solver = dict(
    train=dict(batch_size=8, num_workers=4),
    val=dict(batch_size=8, num_workers=4),
    test=dict(batch_size=8, num_workers=4),
)
workflow = dict(checkpoint_interval=5, val_eval_interval=10, val_start_epoch=25, end_epoch=30)

work_dir = "exps/thumos/e2e_vjepa_sep_te_768x2_160_af8"
