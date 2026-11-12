_base_ = ["thumos_af_fuse_concat.py"]

data_path = "data/thumos-14/features/fuse_iv2_ftkd/"
dataset = dict(train=dict(data_path=data_path), val=dict(data_path=data_path), test=dict(data_path=data_path))

work_dir = "exps/thumos/af_fuse_concat_ftkd"
