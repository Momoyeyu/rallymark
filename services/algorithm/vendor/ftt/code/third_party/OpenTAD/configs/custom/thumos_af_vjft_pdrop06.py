_base_ = ["thumos_actionformer_vjepa21_g_ft_s4_L39.py"]

model = dict(projection=dict(input_pdrop=0.6))

work_dir = "exps/thumos/af_vjft_pdrop06"
