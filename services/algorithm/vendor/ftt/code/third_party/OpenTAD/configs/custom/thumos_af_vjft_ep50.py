_base_ = ["thumos_actionformer_vjepa21_g_ft_s4_L39.py"]

scheduler = dict(max_epoch=50)
workflow = dict(val_start_epoch=45)

work_dir = "exps/thumos/af_vjft_ep50"
