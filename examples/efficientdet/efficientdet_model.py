import tensorflow as tf
import efficientnet_builder
from efficientdet_blocks import ResampleFeatureMap, \
    FPNCells, ClassNet, BoxNet


class EfficientDet(tf.keras.Model):
    """
    EfficientDet model in PAZ.
    # References
        -[Google AutoML repository implementation of EfficientDet](
        https://github.com/google/automl/tree/master/efficientdet)
    """

    def __init__(self,
                 model_name,
                 backbone,
                 image_size,
                 fpn_num_filters,
                 fpn_cell_repeats,
                 box_class_repeats,
                 anchor_scale,
                 min_level,
                 max_level,
                 fpn_weight_method,
                 act_type='swish',
                 fpn_name='BiFPN',
                 num_classes=90,
                 num_scales=3,
                 aspect_ratios=[1.0, 2.0, 0.5],
                 conv_batchnorm_act_pattern=False,
                 use_batchnorm_for_sampling=True,
                 conv_after_downsample=False,
                 separable_conv=True,
                 survival_prob=None,
                 feature_only=False,
                 name=""):
        """Initialize model.
        # Arguments
            config: Configuration of the EfficientDet model.
            name: A string of layer name.
        """
        super().__init__(name=name)
        self.model_name = model_name
        self.backbone = backbone
        self.image_size = image_size
        self.fpn_num_filters = fpn_num_filters
        self.fpn_cell_repeats = fpn_cell_repeats
        self.box_class_repeats = box_class_repeats
        self.anchor_scale = anchor_scale
        self.min_level = min_level
        self.max_level = max_level
        self.fpn_weight_method = fpn_weight_method
        self.num_levels = max_level - min_level + 1
        self.act_type = act_type
        self.fpn_name = fpn_name
        self.num_classes = num_classes
        self.num_scales = num_scales
        self.aspect_ratios = aspect_ratios
        self.conv_batchnorm_act_pattern = conv_batchnorm_act_pattern
        self.use_batchnorm_for_sampling = use_batchnorm_for_sampling
        self.conv_after_downsample = conv_after_downsample
        self.separable_conv = separable_conv
        self.survival_prob = survival_prob
        self.feature_only = feature_only
        self.backbone = efficientnet_builder.build_backbone(
            backbone_name=self.backbone,
            activation_fn=self.act_type,
            survival_prob=self.survival_prob
            )
        self.resample_layers = []
        for level in range(6, self.max_level + 1):
            self.resample_layers.append(ResampleFeatureMap(
                feature_level=(level - self.min_level),
                target_num_channels=self.fpn_num_filters,
                use_batchnorm=self.use_batchnorm_for_sampling,
                conv_after_downsample=self.conv_after_downsample,
                name='resample_p%d' % level,
            ))

        self.fpn_cells = FPNCells(
            fpn_name=self.fpn_name,
            min_level=self.min_level,
            max_level=self.max_level,
            fpn_weight_method=self.fpn_weight_method,
            fpn_cell_repeats=self.fpn_cell_repeats,
            fpn_num_filters=self.fpn_num_filters,
            use_batchnorm_for_sampling=self.use_batchnorm_for_sampling,
            conv_after_downsample=self.conv_after_downsample,
            conv_batchnorm_act_pattern=self.conv_batchnorm_act_pattern,
            separable_conv=self.separable_conv,
            act_type=self.act_type)

        self.num_anchors = len(self.aspect_ratios) * self.num_scales
        self.num_filters = self.fpn_num_filters
        self.class_net = ClassNet(
            num_classes=self.num_classes,
            num_anchors=self.num_anchors,
            num_filters=self.num_filters,
            min_level=self.min_level,
            max_level=self.max_level,
            act_type=self.act_type,
            repeats=self.box_class_repeats,
            separable_conv=self.separable_conv,
            survival_prob=self.survival_prob,
            feature_only=self.feature_only,
        )

        self.box_net = BoxNet(
            num_anchors=self.num_anchors,
            num_filters=self.num_filters,
            min_level=self.min_level,
            max_level=self.max_level,
            act_type=self.act_type,
            repeats=self.box_class_repeats,
            separable_conv=self.separable_conv,
            survival_prob=self.survival_prob,
            feature_only=self.feature_only,
        )

    def call(self, images, training=False):
        """Build EfficientDet model.
        # Arguments
            images: Tensor, indicating the image input to the architecture.
            training: Bool, whether EfficientDet architecture is trained.
        """

        # Efficientnet backbone features
        all_features = self.backbone(images,
                                     training=training,
                                     features_only=True)

        features = all_features[self.min_level:
                                self.max_level + 1]

        # Build additional input features that are not from backbone.
        for resample_layer in self.resample_layers:
            features.append(resample_layer(features[-1], training, None))

        # BiFPN layers
        fpn_features = self.fpn_cells(features, training)

        # Classification head
        class_outputs = self.class_net(fpn_features, training)

        # Box regression head
        box_outputs = self.box_net(fpn_features, training)

        return class_outputs, box_outputs