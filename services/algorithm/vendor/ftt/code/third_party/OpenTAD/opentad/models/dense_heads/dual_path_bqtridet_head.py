"""Class and localization branches consume distinct multi-scale pathways."""

import torch.nn.functional as F

from opentad.models.builder import HEADS
from opentad.models.dense_heads.boundary_quality_tridet_head import BoundaryQualityTriDetHead


@HEADS.register_module()
class DualPathBoundaryQualityTriDetHead(BoundaryQualityTriDetHead):
    def _dense_predictions(self, feat_list, mask_list, training):
        semantic, localization = feat_list
        cls_pred, reg_pred, start_pred, end_pred = [], [], [], []
        reg_features, quality_pred = [], []
        for level, (cls_input, loc_input, mask) in enumerate(zip(semantic, localization, mask_list)):
            cls_feat = cls_input
            reg_feat = loc_input
            # Boundary bins and proposal refinement use the localization path.
            boundary_feat = loc_input.detach() + self.boundary_grad_scale * (loc_input - loc_input.detach()) if training else loc_input.detach()
            start_feat = boundary_feat
            end_feat = boundary_feat
            for i in range(self.num_convs):
                cls_feat, _ = self.cls_convs[i](cls_feat, mask)
                reg_feat, _ = self.reg_convs[i](reg_feat, mask)
                start_feat, _ = self.cls_start_convs[i](start_feat, mask)
                end_feat, _ = self.cls_end_convs[i](end_feat, mask)
            cls_pred.append(self.cls_head(cls_feat))
            reg_pred.append(F.relu(self.scale[level](self.reg_head(reg_feat))))
            start_pred.append(self.cls_start_head(start_feat))
            end_pred.append(self.cls_end_head(end_feat))
            reg_features.append(reg_feat)
            quality_pred.append(self.quality_head(reg_feat))
        points = self.prior_generator(semantic)
        return cls_pred, reg_pred, start_pred, end_pred, reg_features, quality_pred, points
