_base_ = ["thumos_af_fuse_concat.py"]

model = dict(projection=dict(type="StreamDropConcatProj", stream_channels=[3200, 1408], stream_drop=0.2, input_pdrop=0.2))

work_dir = "exps/thumos/af_fuse_concat_sd02"
