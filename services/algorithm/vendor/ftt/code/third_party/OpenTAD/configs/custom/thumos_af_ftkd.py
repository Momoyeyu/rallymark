_base_ = ["thumos_actionformer_vjepa21_g_ft_s4_L39.py"]

data_path = "data/thumos-14/features/vjepa21_g_ftkd_s4_L39/"
dataset = dict(train=dict(data_path=data_path), val=dict(data_path=data_path), test=dict(data_path=data_path))

work_dir = "exps/thumos/af_ftkd"
