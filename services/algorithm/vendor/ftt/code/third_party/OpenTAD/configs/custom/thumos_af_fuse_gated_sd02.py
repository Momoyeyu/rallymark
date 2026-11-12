_base_ = ["thumos_af_fuse_concat.py"]

model = dict(projection=dict(type="GatedFusionProj", stream_channels=[3200, 1408], fuse_channels=512, stream_drop=0.2))

work_dir = "exps/thumos/af_fuse_gated_sd02"
