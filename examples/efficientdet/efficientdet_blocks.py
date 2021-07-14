import itertools
import numpy as np
import tensorflow as tf
from tensorflow.keras.layers import Layer, \
    BatchNormalization, \
    Conv2D, \
    SeparableConv2D, \
    MaxPooling2D, \
    AveragePooling2D
from utils import get_activation_fn, get_drop_connect


def bifpn_configuration(min_level, max_level, weight_method):
    """A dynamic bifpn configuration that can adapt to
    different min/max levels.
    # Arguments
        min_level: Integer. EfficientNet feature minimum level.
        Level decides the activation map size,
        eg: For an input image of 640 x 640,
        the activation map resolution at level 3 is
        (640 / (2 ^ 3)) x (640 / (2 ^ 3)).
        max_level: Integer. EfficientNet feature maximum level.
        Level decides the activation map size,
        eg: For an input image of 640 x 640,
        the activation map resolution at level 3 is
        (640 / (2 ^ 3)) x (640 / (2 ^ 3)).
        weight_method: String. FPN weighting methods for feature fusion.
    # Returns
        bifpn_config: Dictionary. Contains the nodes and offsets
        for building the FPN.
    """
    bifpn_config = dict()
    bifpn_config['weight_method'] = weight_method or 'fastattn'

    # Node id starts from the input features and monotically
    # increase whenever a new node is added.
    # Example for P3 - P7:
    # Px dimension = input_image_dimension / (2 ** x)
    #     Input    Top-down   Bottom-up
    #     -----    --------   ---------
    #     P7 (4)              P7" (12)
    #     P6 (3)    P6' (5)   P6" (11)
    #     P5 (2)    P5' (6)   P5" (10)
    #     P4 (1)    P4' (7)   P4" (9)
    #     P3 (0)              P3" (8)
    # The node ids are provided in the brackets for a particular
    # feature level x, denoted by Px.
    # So output would be like:
    # [
    #   {'feature_level': 6, 'inputs_offsets': [3, 4]},  # for P6'
    #   {'feature_level': 5, 'inputs_offsets': [2, 5]},  # for P5'
    #   {'feature_level': 4, 'inputs_offsets': [1, 6]},  # for P4'
    #   {'feature_level': 3, 'inputs_offsets': [0, 7]},  # for P3"
    #   {'feature_level': 4, 'inputs_offsets': [1, 7, 8]},  # for P4"
    #   {'feature_level': 5, 'inputs_offsets': [2, 6, 9]},  # for P5"
    #   {'feature_level': 6, 'inputs_offsets': [3, 5, 10]},  # for P6"
    #   {'feature_level': 7, 'inputs_offsets': [4, 11]},  # for P7"
    # ]
    num_levels = max_level - min_level + 1
    node_ids = {min_level + level_id: [level_id]
                for level_id in range(num_levels)}
    id_count = itertools.count(num_levels)
    nodes = []
    # Top-down path
    for level in range(max_level - 1, min_level - 1, -1):
        nodes.append({
            'feature_level': level,
            'inputs_offsets': [node_ids[level][-1],
                               node_ids[level + 1][-1]]
        })
        node_ids[level].append(next(id_count))
    # Bottom-up path
    for level in range(min_level + 1, max_level + 1):
        nodes.append({
            'feature_level': level,
            'inputs_offsets': node_ids[level] + [node_ids[level - 1][-1]]
        })
        node_ids[level].append(next(id_count))
    bifpn_config['nodes'] = nodes
    return bifpn_config


def get_fpn_configuration(fpn_name, min_level, max_level, fpn_weight_method):
    """Provides the fpn configuration that can adapt to
    different min/max levels.
    # Arguments
        fpn_name: String. Name of the FPN, eg: BiFPN.
        min_level: Integer. EfficientNet feature minimum level.
        Level decides the activation map size,
        eg: For an input image of 640 x 640,
        the activation map resolution at level 3 is
        (640 / (2 ^ 3)) x (640 / (2 ^ 3)).
        max_level: Integer. EfficientNet feature maximum level.
        Level decides the activation map size,
        eg: For an input image of 640 x 640,
        the activation map resolution at level 3 is
        (640 / (2 ^ 3)) x (640 / (2 ^ 3)).
        weight_method: String. FPN weighting methods for feature fusion.
    # Returns
        bifpn_config: Dictionary. Contains the nodes and offsets
        for building the FPN.
    """
    if fpn_name == 'BiFPN':
        return bifpn_configuration(min_level, max_level, fpn_weight_method)
    else:
        raise NotImplementedError('FPN name not found.')


class ResampleFeatureMap(Layer):
    """Resample feature maps for downsampling or upsampling
     to create coarser or finer additional feature maps."""
    def __init__(self,
                 feature_level,
                 target_num_channels,
                 use_batchnorm=False,
                 conv_after_downsample=False,
                 pooling_type='max',
                 upsampling_type='nearest',
                 name='resample_p0'):
        super().__init__(name=name)
        self.feature_level = feature_level
        self.target_num_channels = target_num_channels
        self.use_batchnorm = use_batchnorm
        self.conv_after_downsample = conv_after_downsample
        self.pooling_type = pooling_type
        self.upsampling_type = upsampling_type
        self.conv2d = Conv2D(self.target_num_channels,
                             (1, 1),
                             padding='same',
                             data_format='channels_last',
                             name='conv2d')
        self.batchnorm = BatchNormalization(axis=-1,
                                            momentum=0.99,
                                            epsilon=1e-3,
                                            center=True,
                                            scale=True,
                                            beta_initializer='zeros',
                                            gamma_initializer='ones',
                                            name='bn')
        if pooling_type in ['max', 'average']:
            self.pooling_type = pooling_type
        else:
            raise ValueError('Unsupported pooling type {}.'.
                             format(pooling_type))

    def _pool2d(self, features, H, W, H_target, W_target):
        """Pool the inputs to target height and width."""
        H_stride = int((H - 1) // H_target + 1)
        W_stride = int((W - 1) // W_target + 1)
        if self.pooling_type == 'max':
            return MaxPooling2D(
                pool_size=[H_stride + 1, W_stride + 1],
                strides=[H_stride, W_stride],
                padding='SAME',
                data_format='channels_last')(features)
        if self.pooling_type == 'average':
            return AveragePooling2D(
                pool_size=[H_stride + 1, W_stride + 1],
                strides=[H_stride, W_stride],
                padding='SAME',
                data_format='channels_last')(features)

    def _upsample2d(self, features, H_target, W_target):
        return tf.cast(
            tf.compat.v1.image.resize_nearest_neighbor(
                tf.cast(features, tf.float32), [H_target, W_target]),
            features.dtype)

    def _apply_1x1_conv(self, feature, training, num_channels):
        """Apply 1x1 conv to change layer width if necessary."""
        if num_channels != self.target_num_channels:
            feature = self.conv2d(feature)
            if self.use_batchnorm:
                feature = self.batchnorm(feature, training=training)
        return feature

    def call(self, feature, training, all_features):
        hwc_idx = (1, 2, 3)
        H, W, num_channels = [feature.shape.as_list()[i] for i in hwc_idx]
        if all_features:
            target_feature_shape = \
                all_features[self.feature_level].shape.as_list()
            H_target, W_target, _ = [target_feature_shape[i] for i in hwc_idx]
        else:
            # Default to downsampling if all_features is empty.
            H_target, W_target = (H + 1) // 2, (W + 1) // 2

        # If conv_after_downsample is True, when downsampling, apply 1x1 after
        # downsampling for efficiency.
        if H > H_target and W > W_target:
            if not self.conv_after_downsample:
                feature = self._apply_1x1_conv(feature,
                                               training,
                                               num_channels)
            feature = self._pool2d(feature,
                                   H,
                                   W,
                                   H_target,
                                   W_target)
            if self.conv_after_downsample:
                feature = self._apply_1x1_conv(feature,
                                               training,
                                               num_channels)
        elif H <= H_target and W <= W_target:
            feature = self._apply_1x1_conv(feature, training, num_channels)
            if H < H_target or W < W_target:
                feature = self._upsample2d(feature,
                                           H_target,
                                           W_target)
        else:
            raise ValueError('Incompatible Resampling : feature shape {}x{} \
            target_shape: {}x{}'.format(H,
                                        W,
                                        H_target,
                                        W_target))
        return feature


class FPNCells(Layer):
    """Set of FPN Cells."""
    def __init__(self,
                 fpn_name,
                 min_level,
                 max_level,
                 fpn_weight_method,
                 fpn_cell_repeats,
                 fpn_num_filters,
                 use_batchnorm_for_sampling,
                 conv_after_downsample,
                 conv_batchnorm_act_pattern,
                 separable_conv,
                 act_type,
                 name='fpn_cells'):
        super().__init__(name=name)
        self.fpn_name = fpn_name
        self.min_level = min_level
        self.max_level = max_level
        self.fpn_weight_method = fpn_weight_method
        self.fpn_cell_repeats = fpn_cell_repeats
        self.fpn_num_filters = fpn_num_filters
        self.use_batchnorm_for_sampling = use_batchnorm_for_sampling
        self.conv_after_downsample = conv_after_downsample
        self.conv_batchnorm_act_pattern = conv_batchnorm_act_pattern
        self.separable_conv = separable_conv
        self.act_type = act_type
        self.fpn_config = get_fpn_configuration(self.fpn_name,
                                                self.min_level,
                                                self.max_level,
                                                self.fpn_weight_method
                                                )
        self.cells = [
            FPNCell(
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
                act_type=self.act_type,
                name='cell_%d' % repeats)
            for repeats in range(self.fpn_cell_repeats)]

    def call(self, features, training):
        for cell in self.cells:
            cell_features = cell(features, training)
            features = []
            for level in range(self.min_level, self.max_level + 1):
                for fnode_arg, fnode in \
                        enumerate(reversed(self.fpn_config['nodes'])):
                    if fnode['feature_level'] == level:
                        features.append(cell_features[-1 - fnode_arg])
                        break
        return features


class FPNCell(Layer):
    """A single FPN cell."""
    def __init__(self,
                 fpn_name,
                 min_level,
                 max_level,
                 fpn_weight_method,
                 fpn_cell_repeats,
                 fpn_num_filters,
                 use_batchnorm_for_sampling,
                 conv_after_downsample,
                 conv_batchnorm_act_pattern,
                 separable_conv,
                 act_type,
                 name='fpn_cell'):
        super().__init__(name=name)
        self.fpn_name = fpn_name
        self.min_level = min_level
        self.max_level = max_level
        self.fpn_weight_method = fpn_weight_method
        self.fpn_cell_repeats = fpn_cell_repeats
        self.fpn_num_filters = fpn_num_filters
        self.use_batchnorm_for_sampling = use_batchnorm_for_sampling
        self.conv_after_downsample = conv_after_downsample
        self.conv_batchnorm_act_pattern = conv_batchnorm_act_pattern
        self.separable_conv = separable_conv
        self.act_type = act_type
        self.fpn_config = get_fpn_configuration(self.fpn_name,
                                                self.min_level,
                                                self.max_level,
                                                self.fpn_weight_method
                                                )
        self.fnodes = []
        for fnode_cfg_arg, fnode_cfg in enumerate(self.fpn_config['nodes']):
            fnode = FNode(
                fnode_cfg['feature_level'] - self.min_level,
                fnode_cfg['inputs_offsets'],
                self.fpn_num_filters,
                self.use_batchnorm_for_sampling,
                self.conv_after_downsample,
                self.conv_batchnorm_act_pattern,
                self.separable_conv,
                self.act_type,
                weight_method=self.fpn_weight_method,
                name='fnode%d' % fnode_cfg_arg)
            self.fnodes.append(fnode)

    def call(self, features, training):
        def _call(features):
            for fnode in self.fnodes:
                features = fnode(features, training)
            return features
        return _call(features)


def sum_nodes(nodes):
    """A customized function to add up a list of tensors."""
    new_node = nodes[0]
    for n in nodes[1:]:
        new_node = new_node + n
    return new_node


class FNode(Layer):
    """A keras layer implementing BiFPN node."""
    def __init__(self,
                 feature_level,
                 inputs_offsets,
                 fpn_num_filters,
                 use_batchnorm_for_sampling,
                 conv_after_downsample,
                 conv_batchnorm_act_pattern,
                 separable_conv,
                 act_type,
                 weight_method,
                 name='fnode'):
        super().__init__(name=name)
        self.feature_level = feature_level
        self.inputs_offsets = inputs_offsets
        self.fpn_num_filters = fpn_num_filters
        self.use_batchnorm_for_sampling = use_batchnorm_for_sampling
        self.conv_after_downsample = conv_after_downsample
        self.conv_batchnorm_act_pattern = conv_batchnorm_act_pattern
        self.separable_conv = separable_conv
        self.act_type = act_type
        self.weight_method = weight_method
        self.resample_layers = []
        self.assign_weights = []

    def fuse_features(self, nodes):
        """Fuse features from different resolutions and return a weighted sum.
        # Arguments
            nodes: a list of tensorflow features at different levels.

        # Returns
            A tensor denoting the fused features.
        """
        dtype = nodes[0].dtype
        if self.weight_method == 'attn':
            edge_weights = []
            for weight in self.assign_weights:
                edge_weights.append(tf.cast(weight, dtype=dtype))
            normalized_weights = tf.nn.softmax(tf.stack(edge_weights))
            nodes = tf.stack(nodes, axis=-1)
            new_node = tf.reduce_sum(nodes * normalized_weights, -1)
        elif self.weight_method == 'fastattn':
            edge_weights = []
            for weight in self.assign_weights:
                edge_weights.append(tf.nn.relu(tf.cast(weight, dtype=dtype)))
            weight_sum = sum_nodes(edge_weights)
            for i in range(len(nodes)):
                nodes[i] = nodes[i] * edge_weights[i] / (weight_sum + 0.0001)
            new_node = sum_nodes(nodes)
        elif self.weight_method == 'sum':
            new_node = sum_nodes(nodes)
        else:
            raise ValueError('unknown weight_method %s' % self.weight_method)
        return new_node

    def _add_scalar_multidimensional_weights(self, initializer, shape=None):
        for input_offset_arg, _ in enumerate(self.inputs_offsets):
            name = 'WSM' + ('' if input_offset_arg == 0
                            else '_' + str(input_offset_arg))
            self.assign_weights.append(self.add_weight(initializer=initializer,
                                                       name=name,
                                                       shape=shape))

    def build(self, features_shape):
        for input_offset_arg, input_offset in enumerate(self.inputs_offsets):
            name = 'resample_{}_{}_{}'.format(input_offset_arg,
                                              input_offset,
                                              len(features_shape))
            self.resample_layers.append(ResampleFeatureMap(
                feature_level=self.feature_level,
                target_num_channels=self.fpn_num_filters,
                use_batchnorm=self.use_batchnorm_for_sampling,
                conv_after_downsample=self.conv_after_downsample,
                name=name
            ))

        if self.weight_method == 'attn':
            self._add_scalar_multidimensional_weights('ones')
        elif self.weight_method == 'fastattn':
            self._add_scalar_multidimensional_weights('ones')
        self.conv_after_fusion = ConvolutionAfterFusion(
            self.conv_batchnorm_act_pattern,
            self.separable_conv,
            self.fpn_num_filters,
            self.act_type,
            name='op_after_combine{}'.format(len(features_shape))
        )
        self.built = True
        super().build(features_shape)

    def call(self, features, training):
        nodes = []
        for input_offset_arg, input_offset in enumerate(self.inputs_offsets):
            input_node = features[input_offset]
            input_node = self.resample_layers[input_offset_arg](input_node,
                                                                training,
                                                                features)
            nodes.append(input_node)
        new_node = self.fuse_features(nodes)
        new_node = self.conv_after_fusion(new_node)
        return features + [new_node]


class ConvolutionAfterFusion(Layer):
    """Operation after combining input features during feature fusion."""
    def __init__(self,
                 conv_batchnorm_act_pattern,
                 separable_conv,
                 fpn_num_filters,
                 act_type,
                 name='op_after_combine'):
        super().__init__(name=name)
        self.conv_batchnorm_act_pattern = conv_batchnorm_act_pattern
        self.separable_conv = separable_conv
        self.fpn_num_filters = fpn_num_filters
        self.act_type = act_type

        if self.separable_conv:
            conv2d_layer = SeparableConv2D(
                filters=fpn_num_filters,
                kernel_size=(3, 3),
                padding='same',
                use_bias=not self.conv_batchnorm_act_pattern,
                data_format='channels_last',
                name='conv',
                depth_multiplier=1)
        else:
            conv2d_layer = Conv2D(
                filters=fpn_num_filters,
                kernel_size=(3, 3),
                padding='same',
                use_bias=not self.conv_batchnorm_act_pattern,
                data_format='channels_last',
                name='conv'
            )

        self.conv_op = conv2d_layer
        self.batchnorm = BatchNormalization(axis=-1,
                                            momentum=0.99,
                                            epsilon=1e-3,
                                            center=True,
                                            scale=True,
                                            beta_initializer='zeros',
                                            gamma_initializer='ones',
                                            name='bn')

    def call(self, new_node, training):
        if not self.conv_batchnorm_act_pattern:
            new_node = tf.nn.swish(new_node)
        new_node = self.conv_op(new_node)
        new_node = self.batchnorm(new_node, training=training)
        if self.conv_batchnorm_act_pattern:
            new_node = tf.nn.swish(new_node)
        return new_node


class ClassNet(Layer):
    """Object class prediction network."""
    def __init__(self,
                 num_classes=90,
                 num_anchors=9,
                 num_filters=32,
                 min_level=3,
                 max_level=7,
                 act_type='swish',
                 repeats=4,
                 separable_conv=True,
                 survival_prob=None,
                 name='class_net',
                 feature_only=False,
                 **kwargs):
        """Initialize the ClassNet.
        # Arguments
            num_classes: Integer. Number of classes.
            num_anchors: Integer. Number of anchors.
            num_filters: Integer. Number of filters for intermediate layers.
            min_level: Integer. Minimum level for features.
            max_level: Integer. Maximum level for features.
            act_type: String of the activation used.
            repeats: Integer. Number of intermediate layers.
            separable_conv: Bool. True to use separable_conv instead of Conv2D.
            survival_prob: Float. If a value is set then drop connect
                will be used.
            name: String indicating the name of this layer.
            feature_only: Bool. Build the base feature network only.
                Excluding final class head.
            **kwargs: other parameters
        """
        super().__init__(name=name, **kwargs)
        self.num_classes = num_classes
        self.num_anchors = num_anchors
        self.num_filters = num_filters
        self.min_level = min_level
        self.max_level = max_level
        self.repeats = repeats
        self.separable_conv = separable_conv
        self.survival_prob = survival_prob
        self.act_type = act_type
        self.conv_blocks = []
        self.batchnorms = []
        self.feature_only = feature_only

        for repeats_args in range(self.repeats):
            self.conv_blocks.append(
                self.conv2d_layer(separable_conv,
                                  self.num_filters,
                                  kernel_size=3,
                                  bias_initializer=tf.zeros_initializer(),
                                  activation=None,
                                  padding='same',
                                  name='class-%d' % repeats_args))
            batchnorm_per_level = []
            for level in range(self.min_level, self.max_level + 1):
                batchnorm_per_level.append(BatchNormalization(
                    name='class-%d-bn-%d' % (repeats_args, level)))
            self.batchnorms.append(batchnorm_per_level)
        self.classes = self.conv2d_layer(
            separable_conv,
            num_filters=num_classes*num_anchors,
            kernel_size=3,
            bias_initializer=tf.constant_initializer(
                -np.log((1 - 0.01) / 0.01)),
            activation=None,
            padding='same',
            name='class-predict')

    def _conv_batchnorm_act(self, image, level, level_id, training):
        conv_block = self.conv_blocks[level]
        batchnorm = self.batchnorms[level][level_id]
        act_type = self.act_type

        def _call(image):
            original_image = image
            image = conv_block(image)
            image = batchnorm(image, training=training)
            if self.act_type:
                image = get_activation_fn(image, act_type)
            if level > 0 and self.survival_prob:
                image = get_drop_connect(image, training, self.survival_prob)
                image = image + original_image
            return image

        return _call(image)

    def call(self, features, training, **kwargs):
        """Call ClassNet."""
        class_outputs = []
        for level_id in range(0, self.max_level - self.min_level + 1):
            image = features[level_id]
            for repeat_args in range(self.repeats):
                image = self._conv_batchnorm_act(image,
                                                 repeat_args,
                                                 level_id,
                                                 training)
            if self.feature_only:
                class_outputs.append(image)
            else:
                class_outputs.append(self.classes(image))
        return class_outputs

    @classmethod
    def conv2d_layer(cls,
                     separable_conv,
                     num_filters,
                     kernel_size,
                     bias_initializer,
                     activation,
                     padding,
                     name
                     ):
        """Gets the conv2d layer in ClassNet class."""
        if separable_conv:
            conv2d_layer = SeparableConv2D(
                filters=num_filters,
                kernel_size=kernel_size,
                bias_initializer=bias_initializer,
                activation=activation,
                padding=padding,
                name=name,
                depth_multiplier=1,
                data_format='channels_last',
                pointwise_initializer=tf.initializers.variance_scaling(),
                depthwise_initializer=tf.initializers.variance_scaling()
            )
        else:
            conv2d_layer = Conv2D(
                filters=num_filters,
                kernel_size=kernel_size,
                bias_initializer=bias_initializer,
                activation=activation,
                padding=padding,
                name=name,
                data_format='channels_last',
                kernel_initializer=tf.random_normal_initializer(stddev=0.01)
            )
        return conv2d_layer


class BoxNet(Layer):
    """Box regression network."""
    def __init__(self,
                 num_anchors=9,
                 num_filters=32,
                 min_level=3,
                 max_level=7,
                 act_type='swish',
                 repeats=4,
                 separable_conv=True,
                 survival_prob=None,
                 name='box_net',
                 feature_only=False,
                 **kwargs):
        """Initialize the BoxNet.
        # Arguments
            num_classes: Integer. Number of classes.
            num_anchors: Integer. Number of anchors.
            num_filters: Integer. Number of filters for intermediate layers.
            min_level: Integer. Minimum level for features.
            max_level: Integer. Maximum level for features.
            act_type: String of the activation used.
            repeats: Integer. Number of intermediate layers.
            separable_conv: Bool. True to use separable_conv instead of Conv2D.
            survival_prob: Float. If a value is set then drop connect
                will be used.
            name: String indicating the name of this layer.
            feature_only: Bool. Build the base feature network only.
                Excluding final class head.
            **kwargs: other parameters
        """
        super().__init__(name=name, **kwargs)
        self.num_anchors = num_anchors
        self.num_filters = num_filters
        self.min_level = min_level
        self.max_level = max_level
        self.repeats = repeats
        self.separable_conv = separable_conv
        self.survival_prob = survival_prob
        self.act_type = act_type
        self.conv_blocks = []
        self.batchnorms = []
        self.feature_only = feature_only

        for repeats_args in range(self.repeats):
            # If using SeparableConv2D
            if self.separable_conv:
                self.conv_blocks.append(SeparableConv2D(
                    filters=self.num_filters,
                    depth_multiplier=1,
                    pointwise_initializer=tf.initializers.variance_scaling(),
                    depthwise_initializer=tf.initializers.variance_scaling(),
                    data_format='channels_last',
                    kernel_size=3,
                    activation=None,
                    bias_initializer=tf.zeros_initializer(),
                    padding='same',
                    name='box-%d' % repeats_args))
            # If using Conv2d
            else:
                self.conv_blocks.append(Conv2D(
                    filters=self.num_filters,
                    kernel_initializer=tf.random_normal_initializer(
                        stddev=0.01),
                    data_format='channels_last',
                    kernel_size=3,
                    activation=None,
                    bias_initializer=tf.zeros_initializer(),
                    padding='same',
                    name='box-%d' % repeats_args))

            batchnorm_per_level = []
            for level in range(self.min_level, self.max_level + 1):
                batchnorm_per_level.append(
                    BatchNormalization(
                        name='box-%d-bn-%d' % (repeats_args, level)))
            self.batchnorms.append(batchnorm_per_level)

        self.boxes = self.boxes_layer(separable_conv,
                                      num_anchors,
                                      name='box-predict')

    def _conv_batchnorm_act(self, image, i, level_id, training):
        conv_block = self.conv_blocks[i]
        batchnorm = self.batchnorms[i][level_id]
        act_type = self.act_type

        def _call(image):
            original_image = image
            image = conv_block(image)
            image = batchnorm(image, training=training)
            if self.act_type:
                image = get_activation_fn(image, act_type)
            if i > 0 and self.survival_prob:
                image = get_drop_connect(image, training, self.survival_prob)
                image = image + original_image
            return image

        return _call(image)

    def call(self, features, training):
        """Call boxnet."""
        box_outputs = []
        for level_id in range(0, self.max_level - self.min_level + 1):
            image = features[level_id]
            for i in range(self.repeats):
                image = self._conv_batchnorm_act(image, i, level_id, training)
            if self.feature_only:
                box_outputs.append(image)
            else:
                box_outputs.append(self.boxes(image))

        return box_outputs

    @classmethod
    def boxes_layer(cls, separable_conv, num_anchors, name):
        """Gets the conv2d layer in BoxNet class."""
        if separable_conv:
            return SeparableConv2D(
                filters=4 * num_anchors,
                depth_multiplier=1,
                pointwise_initializer=tf.initializers.variance_scaling(),
                depthwise_initializer=tf.initializers.variance_scaling(),
                data_format='channels_last',
                kernel_size=3,
                activation=None,
                bias_initializer=tf.zeros_initializer(),
                padding='same',
                name=name)
        else:
            return Conv2D(
                filters=4 * num_anchors,
                kernel_initializer=tf.random_normal_initializer(stddev=0.01),
                data_format='channels_last',
                kernel_size=3,
                activation=None,
                bias_initializer=tf.zeros_initializer(),
                padding='same',
                name=name)