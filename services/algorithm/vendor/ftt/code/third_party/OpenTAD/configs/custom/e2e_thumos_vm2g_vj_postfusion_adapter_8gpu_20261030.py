"""THUMOS14 8-GPU control: two fixed video encoders, one post-fusion adapter."""
_base_ = ["e2e_thumos_videomaev2g_vjepa_kdbd_768x1_160_tridet_full.py"]

model = dict(
    backbone=dict(type="FrozenDualBackboneWrapper"),
    projection=dict(type="PostFusionTemporalAdapterTriDetProj", adapter_hidden=16384, adapter_kernel=3),
)
optimizer = dict(_delete_=True, type="AdamW", lr=1e-4, weight_decay=0.05, paramwise=True)
solver = dict(
    train=dict(batch_size=8, num_workers=2),
    val=dict(batch_size=8, num_workers=2),
    test=dict(batch_size=8, num_workers=2),
)
workflow = dict(checkpoint_interval=2)
work_dir = "exps/thumos/e2e_vm2g_vj_postfusion_adapter_8gpu_20261030"
