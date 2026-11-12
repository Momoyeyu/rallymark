# standardised concat + stream drop 0.4 on IV2 + V-JEPA fine-tuned with KD + boundary losses
_base_ = ["thumos_af_fuse_znorm_sd04.py"]

data_path = "data/thumos-14/features/fuse_iv2_ftkdbd/"
dataset = dict(train=dict(data_path=data_path), val=dict(data_path=data_path), test=dict(data_path=data_path))
model = dict(projection=dict(stats="/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/data/opentad/thumos-14/features/fuse_iv2_ftkdbd_stats.npz"))

work_dir = "exps/thumos/af_fuse_znorm_sd04_ftkdbd"
