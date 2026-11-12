# End-to-end V-JEPA 2.1-g (initialised from our KD + boundary snippet fine-tuning, frozen) + temporal adapters
# (TIA conv + whole-window attention, opentad/models/backbones/vjepa_adapter.py) + ActionFormer.
# Same data / schedule as AdaTAD e2e_thumos_videomaev2_g_768x1_160_adapter (768 frames x stride 4, 160^2),
# global batch 4 (1 per GPU on 4 GPUs). Adapter/det lr kept at AdaTAD-g's 1e-4 (not linearly scaled — 2e-4
# NaN'd on DSW). Chunks are 64 frames (V-JEPA clip length) instead of 16.
_base_ = ["../adatad/thumos/e2e_thumos_videomae_s_768x1_160_adapter.py"]

window_size = 768
chunk_num = window_size // 64

model = dict(
    backbone=dict(
        backbone=dict(
            _delete_=True,
            type="VJEPAAdapter",
            ckpt="/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad/exps/vjepa_ft/kdbd/encoder.pt",
            img_size=160,
            chunk_frames=64,
            total_frames=window_size,
            global_attn=True,
            drop_path_rate=0.1,
        ),
        custom=dict(
            pretrain=None,
            pre_processing_pipeline=[
                dict(type="Rearrange", keys=["frames"], ops="b n c (t1 t) h w -> (b t1) n c t h w", t1=chunk_num),
            ],
            post_processing_pipeline=[
                dict(type="Reduce", keys=["feats"], ops="b n c t h w -> b c t", reduction="mean"),
                dict(type="Rearrange", keys=["feats"], ops="(b t1) c t -> b c (t1 t)", t1=chunk_num),
                dict(type="Interpolate", keys=["feats"], size=window_size),
            ],
        ),
    ),
    projection=dict(in_channels=1408),
)

# batch_size is global (split over GPUs): 4 GPUs x 1 window.
solver = dict(
    train=dict(batch_size=4, num_workers=4),
    val=dict(batch_size=4, num_workers=4),
    test=dict(batch_size=4, num_workers=4),
)
optimizer = dict(lr=1e-4, backbone=dict(custom=[dict(name="adapter", lr=1e-4, weight_decay=0.05)]))
workflow = dict(checkpoint_interval=10, val_eval_interval=4, val_start_epoch=39, end_epoch=60)

work_dir = "exps/thumos/e2e_vjepa_kdbd_768x1_160_af"
