"""One-round soft parent-child association for two-level TAD predictions.

The module consumes predicted intervals and instance features. It never uses
ground-truth intervals in its forward pass. Training supervision is supplied
separately through matched instance IDs.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


class SoftParentLink(nn.Module):
    def __init__(self, input_dim=512, hidden_dim=128):
        super().__init__()
        self.action_proj = nn.Sequential(nn.Linear(input_dim, hidden_dim), nn.ReLU())
        self.parent_proj = nn.Sequential(nn.Linear(input_dim, hidden_dim), nn.ReLU())
        self.pair = nn.Sequential(
            nn.Linear(2 * hidden_dim + 7, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )
        self.none = nn.Linear(hidden_dim + 1, 1)

    def forward(self, action_intervals, parent_intervals, action_scores,
                parent_scores, action_features, parent_features, window_length):
        na, nr = action_intervals.shape[0], parent_intervals.shape[0]
        if action_intervals.shape != (na, 2) or parent_intervals.shape != (nr, 2):
            raise ValueError("Intervals must have shape [N, 2]")
        if action_features.shape[0] != na or parent_features.shape[0] != nr:
            raise ValueError("Instance feature counts differ from interval counts")
        if window_length <= 0:
            raise ValueError("window_length must be positive")
        ah = self.action_proj(action_features.float())
        ph = self.parent_proj(parent_features.float())
        none_logits = self.none(torch.cat((ah, action_scores.float().reshape(-1, 1)), -1))
        if nr == 0:
            return none_logits, none_logits.softmax(-1)

        a = action_intervals.float()[:, None, :]
        r = parent_intervals.float()[None, :, :]
        alen = (a[..., 1] - a[..., 0]).clamp_min(1e-4)
        rlen = (r[..., 1] - r[..., 0]).clamp_min(1e-4)
        overlap = (torch.minimum(a[..., 1], r[..., 1]) -
                   torch.maximum(a[..., 0], r[..., 0])).clamp_min(0)
        center_delta = ((a[..., 0] + a[..., 1]) -
                        (r[..., 0] + r[..., 1])) / (2 * window_length)
        geometry = torch.stack((
            overlap / alen, overlap / rlen,
            torch.log(alen / rlen).clamp(-8, 8), center_delta,
            (a[..., 0] - r[..., 0]) / window_length,
            (a[..., 1] - r[..., 1]) / window_length,
            parent_scores.float()[None, :].expand(na, nr),
        ), -1)
        pair_input = torch.cat((
            ah[:, None, :].expand(-1, nr, -1),
            ph[None, :, :].expand(na, -1, -1), geometry,
        ), -1)
        pair_logits = self.pair(pair_input).squeeze(-1)
        logits = torch.cat((pair_logits, none_logits), dim=1)
        return logits, logits.softmax(-1)


def association_loss(logits, action_gt_index, parent_gt_index,
                     gt_action_parent_index):
    """Set-valued relation supervision; -1 action matches are ignored.

    If a reliably matched action has no predicted parent matched to its GT
    parent, NONE is the target. Multiple proposals for one parent are treated
    as a positive set. Indices are local to one video window.
    """
    na, cols = logits.shape
    nr = cols - 1
    if len(action_gt_index) != na or len(parent_gt_index) != nr:
        raise ValueError("Match counts do not agree with relation logits")
    logp = F.log_softmax(logits.float(), dim=-1)
    terms = []
    for i, match in enumerate(action_gt_index.tolist()):
        if match < 0:
            continue
        parent = int(gt_action_parent_index[match])
        if parent < 0:
            continue
        positives = torch.where(parent_gt_index == parent)[0]
        if positives.numel():
            terms.append(-torch.logsumexp(logp[i, positives], dim=0))
        else:
            terms.append(-logp[i, nr])
    if not terms:
        return logits.sum() * 0
    return torch.stack(terms).mean()
