import glob
import os
import numpy as np
import random

from paz.abstract import SequentialProcessor, Processor
from paz.pipelines import EncoderPredictor, DecoderPredictor
from paz.pipelines import RandomizeRenderedImage
from paz import processors as pr

from processors import MeasureSimilarity
from processors import MakeDictionary


class ImplicitRotationPredictor(Processor):
    def __init__(self, encoder, decoder, measure, renderer):
        super(ImplicitRotationPredictor, self).__init__()
        self.show_decoded_image = pr.ShowImage('decoded_image', wait=False)
        self.show_closest_image = pr.ShowImage('closest_image', wait=False)
        self.encoder = EncoderPredictor(encoder)
        self.dictionary = MakeDictionary(self.encoder, renderer)()
        self.encoder.add(pr.ExpandDims(0))
        self.encoder.add(MeasureSimilarity(self.dictionary, measure))
        self.decoder = DecoderPredictor(decoder)
        outputs = ['image', 'latent_vector', 'latent_image', 'decoded_image']
        self.wrap = pr.WrapOutput(outputs)

    def call(self, image):
        latent_vector, closest_image = self.encoder(image)
        self.show_closest_image(closest_image)
        decoded_image = self.decoder(latent_vector)
        self.show_decoded_image(decoded_image)
        return self.wrap(image, latent_vector, closest_image, decoded_image)


class DomainRandomizationProcessor(Processor):
    def __init__(self, renderer, image_paths, num_occlusions, split=pr.TRAIN):
        super(DomainRandomizationProcessor, self).__init__()
        self.copy = pr.Copy()
        self.render = pr.Render(renderer)
        self.augment = RandomizeRenderedImage(image_paths, num_occlusions)
        preprocessors = [pr.ConvertColorSpace(pr.RGB2BGR), pr.NormalizeImage()]
        self.preprocess = SequentialProcessor(preprocessors)
        self.split = split

    def call(self):
        input_image, alpha_mask = self.render()
        label_image = self.copy(input_image)
        if self.split == pr.TRAIN:
            input_image = self.augment(input_image, alpha_mask)
        input_image = self.preprocess(input_image)
        label_image = self.preprocess(label_image)
        return input_image, label_image


class DomainRandomization(SequentialProcessor):
    def __init__(self, renderer, size, image_paths,
                 num_occlusions, split=pr.TRAIN):
        super(DomainRandomization, self).__init__()
        self.add(DomainRandomizationProcessor(
            renderer, image_paths, num_occlusions, split))
        self.add(pr.SequenceWrapper(
            {0: {'input_image': [size, size, 3]}},
            {1: {'label_image': [size, size, 3]}}))


class GeneratedImagesProcessor(Processor):
    def __init__(self, path_images, background_images_path, num_occlusions, split=pr.TRAIN):
        super(GeneratedImagesProcessor, self).__init__()
        self.copy = pr.Copy()
        self.augment = RandomizeRenderedImage(background_images_path, num_occlusions)
        preprocessors = [pr.ConvertColorSpace(pr.RGB2BGR), pr.NormalizeImage()]
        self.preprocess = SequentialProcessor(preprocessors)
        self.split = split

        # Total number of images
        self.num_images = len(glob.glob(os.path.join(path_images, "image_original/*")))

        # Load all images into memory to save time
        self.images_original = [np.load(os.path.join(path_images, "image_original/image_original_{}.npy".format(str(i).zfill(7)))) for i in range(self.num_images)]
        self.alpha_original = [np.load(os.path.join(path_images, "alpha_original/alpha_original_{}.npy".format(str(i).zfill(7)))) for i in range(self.num_images)]

    def call(self):
        index = random.randint(0, self.num_images - 1)
        input_image = self.images_original[index]
        alpha_mask = self.alpha_original[index]

        label_image = self.copy(input_image)
        if self.split == pr.TRAIN:
            input_image = self.augment(input_image, alpha_mask)
        input_image = self.preprocess(input_image)
        label_image = self.preprocess(label_image)
        return input_image, label_image


class GeneratedImages(SequentialProcessor):
    def __init__(self, path_images, background_images_path, size,
                 num_occlusions, split=pr.TRAIN):
        super(GeneratedImages, self).__init__()
        self.add(GeneratedImagesProcessor(
            path_images, background_images_path, num_occlusions, split))
        self.add(pr.SequenceWrapper(
            {0: {'input_image': [size, size, 3]}},
            {1: {'label_image': [size, size, 3]}}))
