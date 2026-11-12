_base_ = ["thumos_actionformer_vjepa21_g_ft_s4_L39.py"]

model = dict(rpn_head=dict(label_smoothing=0.1))

work_dir = "exps/thumos/af_vjft_ls01"
