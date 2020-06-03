import numpy as np
import colorsys
import random
import cv2

GREEN = (0, 255, 0)
FONT = cv2.FONT_HERSHEY_SIMPLEX
LINE = cv2.LINE_AA


def draw_circle(image, point, color=GREEN, radius=5):
    """ Draws a cirle in image.
    # Arguments
        image: Numpy array of shape [H, W, 3].
        point: List/tuple of length two indicating (y,x) openCV coordinates.
        color: List of length three indicating BGR color of point.
        radius: Integer indicating the radius of the point to be drawn.
    """
    cv2.circle(image, tuple(point), radius, (0, 0, 0), cv2.FILLED)
    inner_radius = int(.8 * radius)
    cv2.circle(image, tuple(point), inner_radius, tuple(color), cv2.FILLED)


def put_text(image, text, point, scale, color, thickness):
    """Draws text in image.
    # Arguments
        image: Numpy array.
        text: String. Text to be drawn.
        point: Tuple of coordinates indicating the top corner of the text.
        scale: Float. Scale of text.
        color: Tuple of integers. BGR color coordinates.
        thickness: Integer. Thickness of the lines used for drawing text.
    """
    return cv2.putText(image, text, point, FONT, scale, color, thickness, LINE)


def draw_line(image, point_A, point_B, color=GREEN, thickness=5):
    """ Draws a line in image from point_A to point_B.
    # Arguments
        image: Numpy array of shape [H, W, 3].
        point_A: List/tuple of length two indicating (y,x) openCV coordinates.
        point_B: List/tuple of length two indicating (y,x) openCV coordinates.
        color: List of length three indicating BGR color of point.
        thickness: Integer indicating the thickness of the line to be drawn.
    """
    cv2.line(image, tuple(point_A), tuple(point_B), tuple(color), thickness)


def draw_rectangle(image, corner_A, corner_B, color, thickness):
    """ Draws a filled rectangle from corner_A to corner_B.
    # Arguments
        image: Numpy array of shape [H, W, 3].
        corner_A: List/tuple of length two indicating (y,x) openCV coordinates.
        corner_B: List/tuple of length two indicating (y,x) openCV coordinates.
        color: List of length three indicating BGR color of point.
        thickness: Integer/openCV Flag. Thickness of rectangle line.
            or for filled use cv2.FILLED flag.
    """
    return cv2.rectangle(
        image, tuple(corner_A), tuple(corner_B), tuple(color), thickness)


def draw_dot(image, point, color=GREEN, radius=5, filled=True):
    """ Draws a dot (small rectangle) in image.
    # Arguments
        image: Numpy array of shape [H, W, 3].
        point: List/tuple of length two indicating (y,x) openCV coordinates.
        color: List of length three indicating BGR color of point.
        radius: Integer indicating the radius of the point to be drawn.
        filled: Boolean. If `True` rectangle is filled with `color`.
    """
    # drawing outer black rectangle
    point_A = (point[0] - radius, point[1] - radius)
    point_B = (point[0] + radius, point[1] + radius)
    draw_rectangle(image, tuple(point_A), tuple(point_B), (0, 0, 0), filled)

    # drawing innner rectangle with given `color`
    inner_radius = int(.8 * radius)
    point_A = (point[0] - inner_radius, point[1] - inner_radius)
    point_B = (point[0] + inner_radius, point[1] + inner_radius)
    draw_rectangle(image, tuple(point_A), tuple(point_B), color, filled)


def draw_cube(image, points, color=GREEN, thickness=2):
    """ Draws a cube in image.
    # Arguments
        image: Numpy array of shape [H, W, 3].
        points: List of length 8  having each element a list
            of length two indicating (y,x) openCV coordinates.
        color: List of length three indicating BGR color of point.
        thickness: Integer indicating the thickness of the line to be drawn.
    """
    # draw bottom
    draw_line(image, points[0][0], points[1][0], color, thickness)
    draw_line(image, points[1][0], points[2][0], color, thickness)
    draw_line(image, points[3][0], points[2][0], color, thickness)
    draw_line(image, points[3][0], points[0][0], color, thickness)

    # draw top
    draw_line(image, points[4][0], points[5][0], color, thickness)
    draw_line(image, points[6][0], points[5][0], color, thickness)
    draw_line(image, points[6][0], points[7][0], color, thickness)
    draw_line(image, points[4][0], points[7][0], color, thickness)

    # draw sides
    draw_line(image, points[0][0], points[4][0], color, thickness)
    draw_line(image, points[7][0], points[3][0], color, thickness)
    draw_line(image, points[5][0], points[1][0], color, thickness)
    draw_line(image, points[2][0], points[6][0], color, thickness)

    # draw X mark on top
    draw_line(image, points[4][0], points[6][0], color, thickness)
    draw_line(image, points[5][0], points[7][0], color, thickness)

    # draw dots
    # [draw_dot(image, point, color, point_radii) for point in points]


def draw_filled_polygon(image, vertices, color):
    """ Draws filled polygon
    # Arguments
        image: Numpy array.
        vertices: List of elements each having a list
            of length two indicating (y,x) openCV coordinates.
        color: Numpy array specifying BGR color of the polygon.
    """
    cv2.fillPoly(image, [vertices], color)


def draw_random_polygon(image, max_radius_scale=.5):
    height, width = image.shape[:2]
    max_distance = np.max((height, width)) * max_radius_scale
    num_vertices = np.random.randint(3, 7)
    angle_between_vertices = 2 * np.pi / num_vertices
    initial_angle = np.random.uniform(0, 2 * np.pi)
    center = np.random.rand(2) * np.array([width, height])
    vertices = np.zeros((num_vertices, 2), dtype=np.int32)
    for vertex_arg in range(num_vertices):
        angle = initial_angle + (vertex_arg * angle_between_vertices)
        vertex = np.array([np.cos(angle), np.sin(angle)])
        vertex = np.random.uniform(0, max_distance) * vertex
        vertices[vertex_arg] = (vertex + center).astype(np.int32)
    color = np.random.randint(0, 256, 3).tolist()
    draw_filled_polygon(image, vertices, color)
    return image


def lincolor(num_colors, saturation=1, value=1, normalized=False):
    """Creates a list of RGB colors linearly sampled from HSV space with
    randomised Saturation and Value

    # Arguments
        num_colors: Int.
        saturation: Float or `None`. If float indicates saturation.
            If `None` it samples a random value.
        value: Float or `None`. If float indicates value.
            If `None` it samples a random value.
        normalized: Bool. If True, RGB colors are returned between [0, 1]
            if False, RGB colros are between [0, 255].

    # Returns
        List, for which each element contains a list with RGB color

    # References
        [Original implementation](https://github.com/jutanke/cselect)
    """
    RGB_colors = []
    hues = [value / num_colors for value in range(0, num_colors)]
    for hue in hues:

        if saturation is None:
            saturation = random.uniform(0.6, 1)

        if value is None:
            value = random.uniform(0.5, 1)

        RGB_color = colorsys.hsv_to_rgb(hue, saturation, value)
        if not normalized:
            RGB_color = [int(color * 255) for color in RGB_color]
        RGB_colors.append(RGB_color)
    return RGB_colors