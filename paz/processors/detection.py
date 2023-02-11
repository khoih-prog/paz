from __future__ import division

import numpy as np

from ..abstract import Processor, Box2D
from ..backend.boxes import match
from ..backend.boxes import encode
from ..backend.boxes import decode
from ..backend.boxes import offset
from ..backend.boxes import clip
from ..backend.boxes import nms_per_class
from ..backend.boxes import denormalize_box
from ..backend.boxes import make_box_square


class SquareBoxes2D(Processor):
    """Transforms bounding rectangular boxes into square bounding boxes.
    """
    def __init__(self):
        super(SquareBoxes2D, self).__init__()

    def call(self, boxes2D):
        for box2D in boxes2D:
            box2D.coordinates = make_box_square(box2D.coordinates)
        return boxes2D


class DenormalizeBoxes2D(Processor):
    """Denormalizes boxes shapes to be in accordance to the original image size.

    # Arguments:
        image_size: List containing height and width of an image.
    """
    def __init__(self):
        super(DenormalizeBoxes2D, self).__init__()

    def call(self, image, boxes2D):
        shape = image.shape[:2]
        for box2D in boxes2D:
            box2D.coordinates = denormalize_box(box2D.coordinates, shape)
        return boxes2D


class RoundBoxes2D(Processor):
    """Round to integer box coordinates.
    """
    def __init__(self):
        super(RoundBoxes2D, self).__init__()

    def call(self, boxes2D):
        for box2D in boxes2D:
            box2D.coordinates = [int(x) for x in box2D.coordinates]
        return boxes2D


class FilterClassBoxes2D(Processor):
    """Filters boxes with valid class names.

    # Arguments
        valid_class_names: List of strings indicating class names to be kept.
    """
    def __init__(self, valid_class_names):
        self.valid_class_names = valid_class_names
        super(FilterClassBoxes2D, self).__init__()

    def call(self, boxes2D):
        filtered_boxes2D = []
        for box2D in boxes2D:
            if box2D.class_name in self.valid_class_names:
                filtered_boxes2D.append(box2D)
        return filtered_boxes2D


class CropBoxes2D(Processor):
    """Creates a list of images cropped from the bounding boxes.

    # Arguments
        offset_scales: List of floats having x and y scales respectively.
    """
    def __init__(self):
        super(CropBoxes2D, self).__init__()

    def call(self, image, boxes2D):
        image_crops = []
        for box2D in boxes2D:
            x_min, y_min, x_max, y_max = box2D.coordinates
            image_crops.append(image[y_min:y_max, x_min:x_max])
        return image_crops


class ClipBoxes2D(Processor):
    """Clips boxes coordinates into the image dimensions"""
    def __init__(self):
        super(ClipBoxes2D, self).__init__()

    def call(self, image, boxes2D):
        image_height, image_width = image.shape[:2]
        for box2D in boxes2D:
            box2D.coordinates = clip(box2D.coordinates, image.shape[:2])
        return boxes2D


class OffsetBoxes2D(Processor):
    """Offsets the height and widht of a list of ``Boxes2D``.

    # Arguments
        offsets: Float between [0, 1].
    """
    def __init__(self, offsets):
        super(OffsetBoxes2D, self).__init__()
        self.offsets = offsets

    def call(self, boxes2D):
        for box2D in boxes2D:
            box2D.coordinates = offset(box2D.coordinates, self.offsets)
        return boxes2D


class ToBoxes2D(Processor):
    """Transforms boxes from dataset into `Boxes2D` messages.

    # Arguments
        class_names: List of class names ordered with respect to the class
            indices from the dataset ``boxes``.
    """
    def __init__(self, class_names=None, one_hot_encoded=False):
        if class_names is not None:
            self.arg_to_class = dict(zip(range(len(class_names)), class_names))
        self.one_hot_encoded = one_hot_encoded
        super(ToBoxes2D, self).__init__()

    def call(self, boxes):
        numpy_boxes2D, boxes2D = boxes, []
        for numpy_box2D in numpy_boxes2D:
            if self.one_hot_encoded:
                class_name = self.arg_to_class[np.argmax(numpy_box2D[4:])]
            elif numpy_box2D.shape[-1] == 5:
                class_name = self.arg_to_class[numpy_box2D[-1]]
            elif numpy_box2D.shape[-1] == 4:
                class_name = None
            boxes2D.append(Box2D(numpy_box2D[:4], 1.0, class_name))
        return boxes2D


class MatchBoxes(Processor):
    """Match prior boxes with ground truth boxes.

    # Arguments
        prior_boxes: Numpy array of shape (num_boxes, 4).
        iou: Float in [0, 1]. Intersection over union in which prior boxes
            will be considered positive. A positive box is box with a class
            different than `background`.
        variance: List of two floats.
    """
    def __init__(self, prior_boxes, iou=.5):
        self.prior_boxes = prior_boxes
        self.iou = iou
        super(MatchBoxes, self).__init__()

    def call(self, boxes):
        boxes = match(boxes, self.prior_boxes, self.iou)
        return boxes


class EncodeBoxes(Processor):
    """Encodes bounding boxes.

    # Arguments
        prior_boxes: Numpy array of shape (num_boxes, 4).
        variances: List of two float values.
    """
    def __init__(self, prior_boxes, variances=[0.1, 0.1, 0.2, 0.2]):
        self.prior_boxes = prior_boxes
        self.variances = variances
        super(EncodeBoxes, self).__init__()

    def call(self, boxes):
        encoded_boxes = encode(boxes, self.prior_boxes, self.variances)
        return encoded_boxes


class DecodeBoxes(Processor):
    """Decodes bounding boxes.

    # Arguments
        prior_boxes: Numpy array of shape (num_boxes, 4).
        variances: List of two float values.
    """
    def __init__(self, prior_boxes, variances=[0.1, 0.1, 0.2, 0.2]):
        self.prior_boxes = prior_boxes
        self.variances = variances
        super(DecodeBoxes, self).__init__()

    def call(self, boxes):
        decoded_boxes = decode(boxes, self.prior_boxes, self.variances)
        return decoded_boxes


class NonMaximumSuppressionPerClass(Processor):
    """Applies non maximum suppression per class.

    # Arguments
        nms_thresh: Float between [0, 1].
        conf_thresh: Float between [0, 1].
    """
    def __init__(self, nms_thresh=.45, conf_thresh=0.01):
        self.nms_thresh = nms_thresh
        self.conf_thresh = conf_thresh
        super(NonMaximumSuppressionPerClass, self).__init__()

    def call(self, boxes):
        boxes, class_data = nms_per_class(boxes, self.nms_thresh, self.conf_thresh)
        return boxes, class_data


class FilterBoxes(Processor):
    """Filters boxes outputted from function ``detect`` as ``Box2D`` messages.

    # Arguments
        class_names: List of class names.
        conf_thresh: Float between [0, 1].
    """
    def __init__(self, class_names, conf_thresh=0.5):
        self.class_names = class_names
        self.conf_thresh = conf_thresh
        self.arg_to_class = dict(zip(
            list(range(len(self.class_names))), self.class_names))
        super(FilterBoxes, self).__init__()

    def call(self, boxes, class_data):
        boxes = filter_boxes(boxes, class_data, self.conf_thresh)
        return boxes


class CropImage(Processor):
    """Crop images using a list of ``box2D``.
    """
    def __init__(self):
        super(CropImage, self).__init__()

    def call(self, image, box2D):
        x_min, y_min, x_max, y_max = box2D.coordinates
        return image[y_min:y_max, x_min:x_max]


class DivideStandardDeviationImage(Processor):
    """Divide channel-wise standard deviation to image.

    # Arguments
        standard_deviation: List of length 3, containing the
            channel-wise standard deviation.

    # Properties
        standard_deviation: List.

    # Methods
        call()
    """
    def __init__(self, standard_deviation):
        self.standard_deviation = standard_deviation
        super(DivideStandardDeviationImage, self).__init__()

    def call(self, image):
        return image / self.standard_deviation


class ScaledResize(Processor):
    """Resizes image by returning the scales to original image.

    # Arguments
        image_size: Int, desired size of the model input.

    # Properties
        image_size: Int.

    # Methods
        call()
    """
    def __init__(self, image_size):
        self.image_size = image_size
        super(ScaledResize, self).__init__()

    def call(self, image):
        """
        # Arguments
            image: Array, raw input image.
        """
        crop_offset_y = np.array(0)
        crop_offset_x = np.array(0)
        height = np.array(image.shape[0]).astype('float32')
        width = np.array(image.shape[1]).astype('float32')
        image_scale_y = np.array(self.image_size).astype('float32') / height
        image_scale_x = np.array(self.image_size).astype('float32') / width
        image_scale = np.minimum(image_scale_x, image_scale_y)
        scaled_height = (height * image_scale).astype('int32')
        scaled_width = (width * image_scale).astype('int32')
        scaled_image = resize_image(image, (scaled_width, scaled_height))
        scaled_image = scaled_image[
                       crop_offset_y: crop_offset_y + self.image_size,
                       crop_offset_x: crop_offset_x + self.image_size,
                       :]
        output_images = np.zeros((self.image_size,
                                  self.image_size,
                                  image.shape[2]))
        output_images[:scaled_image.shape[0],
                      :scaled_image.shape[1],
                      :scaled_image.shape[2]] = scaled_image
        image_scale = 1 / image_scale
        output_images = output_images[np.newaxis]
        return output_images, image_scale


class RemoveClass(Processor):
    """Remove a particular class from the pipeline.

    # Arguments
        class_names: List, indicating given class names.
        class_arg: Int, index of the class to be removed.
        renormalize: Bool, if true scores are renormalized.

    # Properties
        class_arg: Int.
        renormalize: Bool

    # Methods
        call()
    """
    def __init__(self, class_names, class_arg=None, renormalize=False):
        self.class_arg = class_arg
        self.renormalize = renormalize
        if class_arg is not None:
            del class_names[class_arg]
        super(RemoveClass, self).__init__()

    def call(self, boxes):
        if not self.renormalize and self.class_arg is not None:
            boxes = np.delete(boxes, 4 + self.class_arg, axis=1)
        elif self.renormalize:
            raise NotImplementedError
        return boxes


class CropImage(Processor):
    """Crop images using a list of ``box2D``.
    """
    def __init__(self):
        super(CropImage, self).__init__()

    def call(self, image, box2D):
        x_min, y_min, x_max, y_max = box2D.coordinates
        return image[y_min:y_max, x_min:x_max]
