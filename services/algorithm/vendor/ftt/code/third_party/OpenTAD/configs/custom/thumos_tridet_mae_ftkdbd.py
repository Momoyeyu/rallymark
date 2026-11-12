# TriDet on UCF+THUMOS kdbd fine-tuned VideoMAE V2-g features.
_base_ = ["thumos_tridet_mae.py"]

data_path = "data/thumos-14/features/th14_mae_g_ftkdbd_16_4/"
dataset = dict(
    train=dict(data_path=data_path),
    val=dict(data_path=data_path),
    test=dict(data_path=data_path),
)
work_dir = "exps/thumos/tridet_mae_ftkdbd"
