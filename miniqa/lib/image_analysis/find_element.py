import asyncio
import concurrent.futures
import json
import logging
import multiprocessing
import os
import sys
import time
from pathlib import Path
from typing import IO

import numpy

from miniqa.lib.image_analysis.utils import parse_color, open_image, ImageInput, create_regions_mask_for
from .compare import img_dominant_color, color_diff
from ..config import CACHE_DIR
from ..test_case import test_case_file as tf
from ..test_case.test_case_file import to_parsed_position


# === Public Api ===

async def find_element(
    img: ImageInput,
    text: str,
    background_color: str | None = None,
    location_hint: tf.CoordinatePosition | None = None,
    regions: list[tf.ParsedRegion] | None = None,
    ignore_regions: list[tf.ParsedRegion] | None = None,
) -> tuple[int, int, int, int] | None:
    global _mp_executor

    _mp_executor = _mp_executor or concurrent.futures.ProcessPoolExecutor()

    return await asyncio.get_running_loop().run_in_executor(
        _mp_executor,
        _find_element,
        img,
        text,
        background_color,
        location_hint,
        regions,
        ignore_regions
    )


# === Private Api ===

_mp_executor = None


def _find_element(
    img: ImageInput,
    text: str,
    background_color: str | None = None,
    location_hint: str | tuple[float, float] | None = None,
    regions: list[tf.ParsedRegion] | None = None,
    ignore_regions: list[tf.ParsedRegion] | None = None,
) -> tuple[int, int, int, int] | None:
    """
    Analyse the given image to find an element matching [text] and optionally
    [background_color].

    If multiple matching elements are found, [location_hint] (e.g. "right",
    "bottom", "top-right") is used to pick the closest one.

    :return: (x, y, width, height) or None
    """

    from ppocr_lite.engine import OCRResult, merge_phrase_boxes_fuzzy

    img = open_image(img)
    img_w, img_h = img.shape[1], img.shape[0]

    # Black out everything outside regions, so no text is recognized there:
    img = img * create_regions_mask_for(img, regions, ignore_regions)

    parsed_location_hint = to_parsed_position(location_hint) if location_hint else None
    location_hint_tuple = (parsed_location_hint[0].to_rel(img_w), parsed_location_hint[1].to_rel(img_h)) if location_hint else None
    phrase_to_find = text if not background_color else None

    # OCR:
    s = time.perf_counter()
    word_boxes = _ocr_word_boxes(
        img,
        location_hint_tuple,
        phrase_to_find=phrase_to_find,
    )

    logging.info(f"[find_element] Detected phrases: {json.dumps([b.text for b in word_boxes])} (took {time.perf_counter() - s:.2f}s)")

    if phrase_to_find and len(word_boxes) == 1:  # if we gave it a phrase, the OCR engine did the matching for us
        return word_boxes[0].box.x, word_boxes[0].box.y, word_boxes[0].box.width, word_boxes[0].box.height

    candidates = word_boxes

    # Background-color filter:
    if background_color is not None:
        try:
            target_rgb = parse_color(background_color)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        colour_matched: list[OCRResult] = []
        for candidate in candidates:
            sampled = _dominant_background_color(img, candidate.box)
            dist = color_diff(sampled, target_rgb)
            if dist <= 0.1:  # 10% color threshold; TODO: make this configurable (?)
                colour_matched.append(candidate)

        candidates = colour_matched

    # Phrase matching (exact first, then fuzzy fallback):
    arranged = arrange_text(candidates)
    phrase_tokens = text.split()
    candidates: list[OCRResult] = list(merge_phrase_boxes_fuzzy(arranged, phrase_tokens))

    #if not candidates:
    #    candidates = merge_phrase_boxes_fuzzy(arranged, phrase_tokens)
    #    print(f"[find_element] merge_phrase_boxes_fuzzy candidates for \"{phrase_tokens}\": {candidates} (arranged: {[[w.text for w in l] for l in arranged]})")
    if not candidates:
        return None

    if not candidates:
        return None

    # Location-hint disambiguation:
    if len(candidates) == 1:
        best = candidates[0]
    elif location_hint is not None:
        best = min(
            candidates,
            key=lambda b: _location_score(b, img_w, img_h, location_hint_tuple),
        )
    else:
        # No hint and multiple matches: pick the topmost-leftmost one.
        best = min(candidates, key=lambda b: (b.y, b.x))

    return best.box.x, best.box.y, best.box.width, best.box.height

# === Color utilities ===

def _dominant_background_color(
    img: numpy.ndarray, bbox: 'ppocr_lite.BBox', padding: int = 4
) -> tuple[int, int, int]:
    """
    Sample pixels in a padded border around the bounding box to estimate
    the background color behind the element.
    """

    return img_dominant_color(img, ignore_regions=[
        (
            tf.ParsedCoordinate.abs(value=padding),
            tf.ParsedCoordinate.abs(value=padding),
            tf.ParsedCoordinate.abs(value=bbox.width),
            tf.ParsedCoordinate.abs(value=bbox.height),
        )
    ])


# === Location-hint scoring ===
def _location_score(bbox: 'ppocr_lite.BBox', img_w: int, img_h: int, anchor: tuple[float, float]) -> float:
    """Lower score = closer to the desired region (Euclidean dist in normalised space)."""
    norm_cx = bbox.cx / img_w
    norm_cy = bbox.cy / img_h
    return ((norm_cx - anchor[0]) ** 2 + (norm_cy - anchor[1]) ** 2) ** 0.5


# === OCR helpers ===
try:
    from ppocr_lite import PPOCRLite, arrange_text
    import ppocr_lite.models

    _model_cache_dir = os.environ.get("MINIQA_OCR_MODEL_CACHE_DIR", Path(CACHE_DIR) / 'ocr_models')
    ppocr_lite.models.set_cache_directory(Path(_model_cache_dir))

    if multiprocessing.parent_process() is None:
        installed_models = set(f.name for f in ppocr_lite.models.list_downloaded_models())
        default_model_names = ppocr_lite.models.get_default_model_names()
        if installed_models != set(default_model_names):
            if os.environ.get("MINIQA_SETUP_SKIP_CONFIRM", "0").lower() in ('1', 'yes', 'true'):
                print("Downloading OCR models...")
                ppocr_lite.models.download_default_models()
            else:
                logging.warning(
                    f"OCR models are not yet installed in {ppocr_lite.models.get_cache_directory()}. These models will be "
                    f"downloaded automatically from Huggingface when running the first step that requires OCR (note that this "
                    f"might cause the step to fail due to the time the download takes).\n\n"
                    f"To use OCR without automatic download, place PaddleOCR models in "
                    f"{ppocr_lite.models.get_cache_directory()}, using these filenames: {', '.join(default_model_names)}\n"
                    f"Refer to https://github.com/mityax/ppocr_lite?tab=readme-ov-file#install for more information.\n"
                )

                if input("Download now? [y/N]: ").lower() in ('y', 'yes'):
                    ppocr_lite.models.download_default_models()
except ImportError:
    ppocr_lite = None

_ocr_engine = None


def _ocr_word_boxes(
        img: numpy.ndarray,
        location_hint: tuple[float, float] | None,
        phrase_to_find: str | None = None,
) -> list['ppocr_lite.engine.OCRResult']:
    global _ocr_engine

    if ppocr_lite is None:
        raise ImportError("To use OCR, you need to `pip install miniqa[ocr]`, or use the corresponding container image.")
    if _ocr_engine is None:
        _ocr_engine = ppocr_lite.PPOCRLite()

    if phrase_to_find:
        results = _ocr_engine.check_contains(
            img,
            phrases=[phrase_to_find],
            position_hints=[location_hint] if location_hint else None,
            position_max_dist=0.3 if location_hint else 0,
        )

        results = [] if results[0] is None else results
    else:
        results = _ocr_engine.run(img)

    if not results:
        return []

    logging.debug(f"[find_element]: Word boxes: {results}")

    return results
