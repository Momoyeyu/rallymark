# Ablation of e2e_thumos_vjepa_kdbd_768x1_160_af: adapters keep only the TIA temporal conv (no whole-window
# attention). Same global batch 4 and lr; meant for 2 GPUs x 2 windows.
_base_ = ["e2e_thumos_vjepa_kdbd_768x1_160_af.py"]

model = dict(backbone=dict(backbone=dict(global_attn=False)))

work_dir = "exps/thumos/e2e_vjepa_kdbd_768x1_160_af_noattn"
