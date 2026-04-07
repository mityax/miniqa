from typing import IO

import numpy
from PIL import Image
from PIL.ImageFile import ImageFile

from ..test_case import test_case_file as tf

type ImageInput = str | IO | ImageFile | numpy.ndarray

def open_image(path_or_img: ImageInput) -> numpy.ndarray:
    if isinstance(path_or_img, numpy.ndarray):
        return path_or_img
    if not isinstance(path_or_img, ImageFile):
        path_or_img = Image.open(path_or_img)
    return numpy.array(path_or_img)


def crop_regions(img: numpy.ndarray, regions: list[tf.ParsedRegion] | None, ignore_regions: list[tf.ParsedRegion] | None = None) -> tuple[numpy.ndarray, int]:
    mask = create_regions_mask_for(img, regions, ignore_regions)

    # Compute the number of non-blacked-out pixels:
    color_channels = img.shape[-1]
    retained_pixels = int(mask.sum() / color_channels)

    return img * mask, retained_pixels


def create_regions_mask_for(
    img: numpy.ndarray,
    regions: list[tf.ParsedRegion] | None,
    ignore_regions: list[tf.ParsedRegion] | None,
) -> numpy.ndarray:
    img_height, img_width = img.shape[:2]

    # Create a mask with all ignore regions blacked out:
    ignore_regions_mask = numpy.ones_like(img)
    if ignore_regions:
        for r in ignore_regions:
            x = r[0].to_abs(img_width)
            y = r[1].to_abs(img_height)
            width = r[2].to_abs(img_width)
            height = r[3].to_abs(img_height)
            ignore_regions_mask[y:y + height, x:x + width] = 0

    # Create a mask that is all black except for the given regions:
    if regions:
        regions_mask = numpy.zeros_like(img)
        for r in regions:
            x = r[0].to_abs(img_width)
            y = r[1].to_abs(img_height)
            width = r[2].to_abs(img_width)
            height = r[3].to_abs(img_height)
            regions_mask[y:y + height, x:x + width] = 1
    else:
        regions_mask = numpy.ones_like(img)

    # Create the final mask:
    combined_mask = ignore_regions_mask * regions_mask

    return combined_mask


_CSS_COLORS: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "lime": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "orange": (255, 165, 0),
    "pink": (255, 192, 203),
    "purple": (128, 0, 128),
    "brown": (165, 42, 42),
    "navy": (0, 0, 128),
    "teal": (0, 128, 128),
    "silver": (192, 192, 192),
    "gold": (255, 215, 0),
    "violet": (238, 130, 238),
    "indigo": (75, 0, 130),
    "maroon": (128, 0, 0),
    "olive": (128, 128, 0),
    "beige": (245, 245, 220),
    "ivory": (255, 255, 240),
    "cream": (255, 253, 208),
    "coral": (255, 127, 80),
    "salmon": (250, 128, 114),
    "turquoise": (64, 224, 208),
    "lavender": (230, 230, 250),
}


def parse_color(color_str: str) -> tuple[int, int, int]:
    """Parse a CSS color name or hex string (#rgb / #rrggbb) to an RGB-tuple in the 0-255 range."""
    s = color_str.strip().lower()

    if s in _CSS_COLORS:
        return _CSS_COLORS[s]

    s = s.lstrip("#")

    if len(s) == 3:
        s = "".join(c * 2 for c in s)

    if len(s) == 6:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        return r, g, b

    raise ValueError(f"Unrecognised color: {color_str!r}")

