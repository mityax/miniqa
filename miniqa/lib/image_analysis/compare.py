import numpy as np

from ..image_analysis.utils import open_image, create_regions_mask_for, ImageInput
from ..test_case import test_case_file as tf


def img_difference(
        img: ImageInput,
        ref_img: ImageInput,
        regions: list[tf.ParsedRegion] | None,
        ignore_regions: list[tf.ParsedRegion] | None = None,
        threshold: int=2,
):
    img = open_image(img)
    ref = open_image(ref_img)

    if img.shape != ref.shape:
        return 1

    mask = create_regions_mask_for(img, regions, ignore_regions)

    # Calculate the number of pixels not blacked out by the mask:
    color_channels = img.shape[-1]
    retained_pixels = int(mask.sum() / color_channels)

    diff = np.abs((img - ref) * mask)
    diff_flattened_channels = diff.sum(axis=2)  # sum color channel diffs into one dim

    # Find all pixels that differ more than `threshold`:
    diff_pixels = np.count_nonzero(diff_flattened_channels[diff_flattened_channels > threshold])

    return diff_pixels / retained_pixels


def img_dominant_color(
    img: ImageInput,
    regions: list[tf.ParsedRegion] | None = None,
    ignore_regions: list[tf.ParsedRegion] | None = None,
) -> tuple[int, int, int]:
    """
    Identify the most dominant color in the image and return it as RGB-tuple in the 0-255 range.
    """
    quantize_bits = 6

    image = open_image(img)
    mask = create_regions_mask_for(image, regions or [], ignore_regions or [])

    mask_flat = mask.reshape(-1, mask.shape[-1]).any(axis=1)
    pixels = image.reshape(-1, image.shape[-1])[:, :3]
    pixels = pixels[mask_flat]

    if len(pixels) == 0:
        raise ValueError("Mask produced no valid pixels to analyze.")

    # Quantize: crush 8-bit channels to `quantize_bits` bits
    shift = 8 - quantize_bits
    quantized = (pixels.astype(np.uint32) >> shift)

    # Pack RGB into a single integer for fast counting
    packed = (quantized[:, 0] << (quantize_bits * 2)
              | quantized[:, 1] << quantize_bits
              | quantized[:, 2])

    # Find the most frequent packed color
    counts = np.bincount(packed)
    dom_packed = np.argmax(counts)

    # Unpack and scale back to 8-bit midpoint
    mask_ch = (1 << quantize_bits) - 1
    r = (dom_packed >> (quantize_bits * 2)) & mask_ch
    g = (dom_packed >> quantize_bits) & mask_ch
    b = dom_packed & mask_ch

    mid = (1 << shift) // 2  # e.g. 2 for 6-bit: maps bucket center back to 0-255
    return int(r << shift | mid), int(g << shift | mid), int(b << shift | mid)


def color_diff(color_a: tuple[int, int, int], color_b: tuple[int, int, int]) -> float:
    """Returns the color distance as a float between 0 and 1 (= diff between black and white)."""

    max_dist = np.sqrt(3) * 255  # distance between black (0,0,0) and white (255,255,255)

    return float(np.clip(np.linalg.norm(np.array(color_a) - np.array(color_b)) / max_dist, 0.0, 1.0))

