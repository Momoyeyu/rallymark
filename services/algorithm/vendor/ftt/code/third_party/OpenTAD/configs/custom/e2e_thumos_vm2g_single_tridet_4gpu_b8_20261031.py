"""THUMOS14 VideoMAEv2-G single-stream TriDet control for adapter-position run.

Same 768-frame 160x160 input, seed42, BF16, global batch8, 60 epochs,
TriDet head, validation schedule and post-processing as the dual-adapter run.
Only the VM2-G branch is retained; its layer-20:39 adapters stay trainable.
"""
_base_ = ["e2e_thumos_vm2g_vj_prefusion_adapters_8gpu_20261030.py"]

model = dict(
    backbone=dict(_delete_=True, **_base_.BRANCHES[0]),
    projection=dict(in_channels=1408),
)
solver = dict(
    train=dict(batch_size=8, num_workers=2),
    val=dict(batch_size=8, num_workers=2),
    test=dict(batch_size=8, num_workers=2),
)
work_dir = "exps/thumos/e2e_vm2g_single_tridet_4gpu_b8_20261031"
