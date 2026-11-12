"""THUMOS14 8-GPU: separate online adapters in both video encoders."""
_base_ = ["e2e_thumos_videomaev2g_vjepa_kdbd_768x1_160_tridet_full.py"]
solver = dict(
    train=dict(batch_size=8, num_workers=2),
    val=dict(batch_size=8, num_workers=2),
    test=dict(batch_size=8, num_workers=2),
)
workflow = dict(checkpoint_interval=2)
work_dir = "exps/thumos/e2e_vm2g_vj_prefusion_adapters_8gpu_20261030"
