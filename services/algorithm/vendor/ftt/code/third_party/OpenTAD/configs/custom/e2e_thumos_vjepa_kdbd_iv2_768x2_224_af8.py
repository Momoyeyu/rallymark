# 8-GPU ActionFormer-only input-scale run (768x2_224). Global batch 8 = 1 window/GPU.
# Sparse eval: only epochs 49 and 59 (prior e2e+IV2 AF rose to the end; TriDet peaked ~43 then fell —
# two late checkpoints are enough to judge whether scale beats 76.09).
# lr kept at 1e-4 (do NOT linear-scale with batch; 2e-4 previously NaN'd).
_base_ = ["e2e_thumos_vjepa_kdbd_iv2_768x2_224_af.py"]

solver = dict(
    train=dict(batch_size=8, num_workers=4),
    val=dict(batch_size=8, num_workers=4),
    test=dict(batch_size=8, num_workers=4),
)
optimizer = dict(lr=1e-4, backbone=dict(custom=[dict(name="adapter", lr=1e-4, weight_decay=0.05)]))
workflow = dict(
    checkpoint_interval=10,
    val_eval_interval=10,
    val_start_epoch=49,
    end_epoch=60,
)

work_dir = "exps/thumos/e2e_vjepa_kdbd_iv2_768x2_224_af8"
