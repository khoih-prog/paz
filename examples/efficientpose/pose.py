import numpy as np
from paz.abstract import Processor
import paz.processors as pr
from paz.backend.boxes import change_box_coordinates
from paz.backend.image import lincolor
from efficientpose import EFFICIENTPOSEA
from processors import (ComputeResizingShape, PadImage, ComputeCameraParameter,
                        RegressTranslation, ComputeTxTy, DrawPose6D,
                        ComputeSelectedIndices, ToPose6D)


B_LINEMOD_MEAN, G_LINEMOD_MEAN, R_LINEMOD_MEAN = 103.53, 116.28, 123.675
RGB_LINEMOD_MEAN = (R_LINEMOD_MEAN, G_LINEMOD_MEAN, B_LINEMOD_MEAN)
B_LINEMOD_STDEV, G_LINEMOD_STDEV, R_LINEMOD_STDEV = 57.375, 57.12, 58.395
RGB_LINEMOD_STDEV = (R_LINEMOD_STDEV, G_LINEMOD_STDEV, B_LINEMOD_STDEV)

LINEMOD_CAMERA_MATRIX = np.array([
    [572.41140, 000.00000, 325.26110],
    [000.00000, 573.57043, 242.04899],
    [000.00000, 000.00000, 001.00000]],
    dtype=np.float32)

LINEMOD_OBJECT_SIZES = {
    "ape":         np.array([075.86860000, 077.59920000, 091.76900000]),
    "can":         np.array([100.79160000, 181.79580000, 193.73400000]),
    "cat":         np.array([067.01070000, 127.63300000, 117.45660000]),
    "driller":     np.array([229.47600000, 075.47140000, 208.00200000]),
    "duck":        np.array([104.42920000, 077.40760000, 085.69700000]),
    "eggbox":      np.array([150.18460000, 107.07500000, 069.24140000]),
    "glue":        np.array([036.72110000, 077.86600000, 172.81580000]),
    "holepuncher": np.array([100.88780000, 108.49700000, 090.80000000]),
    }


def get_class_names(dataset_name='LINEMOD'):
    if dataset_name in ['LINEMOD']:
        class_names = ['ape', 'can', 'cat', 'driller', 'duck',
                       'eggbox', 'glue', 'holepuncher']

    return class_names


class DetectAndEstimateSingleShot(Processor):
    def __init__(self, model, class_names, score_thresh, nms_thresh,
                 LINEMOD_CAMERA_MATRIX, LINEMOD_OBJECT_SIZES, preprocess=None,
                 postprocess=None, variances=[1.0, 1.0, 1.0, 1.0],
                 show_boxes2D=False, show_poses6D=True):
        self.model = model
        self.class_names = class_names
        self.score_thresh = score_thresh
        self.nms_thresh = nms_thresh
        self.variances = variances
        self.class_to_sizes = LINEMOD_OBJECT_SIZES
        self.camera_matrix = LINEMOD_CAMERA_MATRIX
        self.colors = lincolor(len(self.class_names))
        self.show_boxes2D = show_boxes2D
        self.show_poses6D = show_poses6D
        if preprocess is None:
            self.preprocess = EfficientPosePreprocess(model)
        if postprocess is None:
            self.postprocess = EfficientPosePostprocess(
                model, class_names, score_thresh, nms_thresh)

        super(DetectAndEstimateSingleShot, self).__init__()
        self.draw_boxes2D = pr.DrawBoxes2D(self.class_names)
        self.wrap = pr.WrapOutput(['image', 'boxes2D', 'poses6D'])

    def _build_draw_pose6D(self, name_to_size, camera_parameter):
        name_to_draw = {}
        iterator = zip(name_to_size.items(), self.colors)
        for (name, object_size), box_color in iterator:
            draw = DrawPose6D(object_size, camera_parameter, box_color)
            name_to_draw[name] = draw
        return name_to_draw

    def call(self, image):
        preprocessed_data = self.preprocess(image)
        preprocessed_image, image_scale, camera_parameter = preprocessed_data
        outputs = self.model(preprocessed_image)
        detections, (rotations, translations) = outputs
        detections = change_box_coordinates(detections)
        outputs = detections, (rotations, translations)
        boxes2D, poses6D = self.postprocess(
            outputs, image_scale, camera_parameter)
        if self.show_boxes2D:
            image = self.draw_boxes2D(image, boxes2D)

        if self.show_poses6D:
            self.draw_pose6D = self._build_draw_pose6D(
                self.class_to_sizes, self.camera_matrix)
            for box2D, pose6D in zip(boxes2D, poses6D):
                image = self.draw_pose6D[box2D.class_name](image, pose6D)
        return self.wrap(image, boxes2D, poses6D)


class EfficientPosePreprocess(Processor):
    def __init__(self, model, mean=RGB_LINEMOD_MEAN,
                 standard_deviation=RGB_LINEMOD_STDEV,
                 camera_matrix=LINEMOD_CAMERA_MATRIX,
                 translation_scale_norm=1000.0):
        super(EfficientPosePreprocess, self).__init__()

        self.compute_resizing_shape = ComputeResizingShape(
            model.input_shape[1])
        self.preprocess = pr.SequentialProcessor([
            pr.SubtractMeanImage(mean),
            pr.DivideStandardDeviationImage(standard_deviation),
            PadImage(model.input_shape[1]),
            pr.CastImage(float),
            pr.ExpandDims(axis=0)])
        self.compute_camera_parameter = ComputeCameraParameter(
            camera_matrix, translation_scale_norm)

    def call(self, image):
        resizing_shape, image_scale = self.compute_resizing_shape(image)
        resize_image = pr.ResizeImage(resizing_shape)
        preprocessed_image = resize_image(image)
        preprocessed_image = self.preprocess(preprocessed_image)
        camera_parameter = self.compute_camera_parameter(image_scale)
        return preprocessed_image, image_scale, camera_parameter


class EfficientPosePostprocess(Processor):
    def __init__(self, model, class_names, score_thresh, nms_thresh,
                 variances=[1.0, 1.0, 1.0, 1.0], class_arg=None):
        super(EfficientPosePostprocess, self).__init__()
        model.prior_boxes = model.prior_boxes * model.input_shape[1]
        self.postprocess_1 = pr.SequentialProcessor([
            pr.Squeeze(axis=None),
            pr.DecodeBoxes(model.prior_boxes, variances),
            pr.RemoveClass(class_names, class_arg)])
        self.scale = pr.ScaleBox()
        self.postprocess_2 = pr.SequentialProcessor([
            pr.NonMaximumSuppressionPerClass(nms_thresh),
            pr.MergeNMSBoxWithClass(),
            pr.FilterBoxes(class_names, score_thresh)])
        self.to_boxes2D = pr.ToBoxes2D(class_names)
        self.round_boxes = pr.RoundBoxes2D()
        self.regress_translation = RegressTranslation(model.translation_priors)
        self.compute_tx_ty = ComputeTxTy()
        self.compute_selections = ComputeSelectedIndices()
        self.squeeze = pr.Squeeze(axis=0)
        self.transform_rotations = pr.Scale(np.pi)
        self.to_pose_6D = ToPose6D(class_names)

    def call(self, model_output, image_scale, camera_parameter):
        detections, (rotations, translations) = model_output
        box_data = self.postprocess_1(detections)
        box_data = self.scale(box_data, 1 / image_scale)
        box_data_all = box_data
        box_data = self.postprocess_2(box_data)
        boxes2D = self.to_boxes2D(box_data)
        boxes2D = self.round_boxes(boxes2D)

        selected_indices = self.compute_selections(box_data_all, box_data)
        rotations = self.squeeze(rotations)
        rotations = rotations[selected_indices]
        rotations = self.transform_rotations(rotations)

        translation_xy_Tz = self.regress_translation(translations)
        translation = self.compute_tx_ty(translation_xy_Tz, camera_parameter)
        translations = translation[selected_indices]

        poses6D = self.to_pose_6D(box_data, rotations, translations)
        return boxes2D, poses6D


class EFFICIENTPOSEALINEMOD(DetectAndEstimateSingleShot):
    def __init__(self, score_thresh=0.60, nms_thresh=0.45,
                 show_boxes2D=False, show_poses6D=True):
        names = get_class_names('LINEMOD')
        model = EFFICIENTPOSEA(num_classes=len(names), base_weights='COCO',
                               head_weights='LINEMOD_OCCLUDED')
        super(EFFICIENTPOSEALINEMOD, self).__init__(
            model, names, score_thresh, nms_thresh,
            LINEMOD_CAMERA_MATRIX, LINEMOD_OBJECT_SIZES,
            show_boxes2D=show_boxes2D, show_poses6D=show_poses6D)
