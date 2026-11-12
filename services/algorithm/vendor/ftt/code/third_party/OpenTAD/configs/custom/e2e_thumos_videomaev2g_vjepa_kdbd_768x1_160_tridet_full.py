"""THUMOS14 dual-online VideoMAEv2-G + V-JEPA end-to-end training."""

_base_ = ["e2e_thumos_videomaev2g_vjepa_kdbd_768x1_160_tridet_pilot.py"]

workflow = dict(
    end_epoch=60,
    checkpoint_interval=10,
    val_eval_interval=4,
    val_start_epoch=39,
)
work_dir = "exps/thumos/e2e_videomaev2g_vjepa_kdbd_768x1_160_tridet_full"
