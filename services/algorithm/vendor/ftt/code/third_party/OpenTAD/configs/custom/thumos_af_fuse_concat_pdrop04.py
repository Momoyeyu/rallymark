_base_ = ["thumos_af_fuse_concat.py"]

model = dict(projection=dict(input_pdrop=0.4))

work_dir = "exps/thumos/af_fuse_concat_pdrop04"
