_base_ = ["thumos_actionformer_vjepa21_g_L39.py"]

data_path = "data/thumos-14/features/vjepa21_g_256_s2_L39/"
dataset = dict(
    train=dict(data_path=data_path, offset_frames=2),
    val=dict(data_path=data_path, offset_frames=2),
    test=dict(data_path=data_path, offset_frames=2),
)

work_dir = "exps/thumos/actionformer_vjepa21_g_s2_L39"
