"""Evaluate the trained paired-subset model on audited ANet validation media.

The audited manifest may be incomplete. Check summary.json before reporting.
"""
_base_ = ['e2e_anet_paired_iv2_vj_tridet.py']

root = '/mnt/keep_aicoach/users/yubo/datasets/vision/videomind_tad'
media = root + '/data/opentad/activitynet-1.3/full_validation_media_20261028'
dataset = dict(
    test=dict(ann_file=media + '/annotations.json', data_path=media + '/videos'),
)
evaluation = dict(ground_truth_filename=media + '/annotations.json')
work_dir = 'exps/anet/e2e_paired_iv2_vj_tridet_validation_media_20261028'
