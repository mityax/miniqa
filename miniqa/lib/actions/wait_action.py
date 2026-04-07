import asyncio
import logging
import os
import tempfile
import time

import numpy
from PIL.Image import Image
from ppocr_lite.utils import log_perf

from miniqa.lib.test_case.test_case_file import FindElement
from ..config import CONFIG
from ..errors import TestException
from ..image_analysis.compare import img_difference, img_dominant_color, color_diff
from ..image_analysis.find_element import find_element
from ..image_analysis.utils import open_image, parse_color
from ..qemu import QEMUWorker
from ..test_case import test_case_file as f
from ..utils import format_color


async def run_wait_step(step: f.WaitStep, worker: QEMUWorker):
    """
    Run a WaitStep on the given [worker].
    """

    start = time.monotonic()

    last_pth: str | None = None
    cached_last_img: numpy.ndarray | None = None

    diff_threshold = f.to_ratio(step.wait.diff)  # if `step.wait.for_` is given max diff, otherwise min diff to previous image
    regions        = f.to_parsed_regions(step.wait.regions)
    ignore_regions = f.to_parsed_regions(CONFIG.ignore_regions)
    timeout        = f.to_seconds(step.wait.timeout)
    check_interval = f.to_seconds(step.wait.check_interval) if step.wait.check_interval else max(0.03, timeout / 90)

    for_img: tuple[str, numpy.ndarray] | None = None  # (path, Image)
    for_dominant_color: tuple[int, int, int] | None = None
    for_find_element: f.FindElement | None = None

    if isinstance(step.wait.for_, str) and not step.wait.for_.startswith('#'):
        p = _find_path(step.wait.for_, 'ppm', 'refs')
        for_img = (p, open_image(p))
    elif isinstance(step.wait.for_, f.WaitForArgs):
        for_dominant_color = parse_color(step.wait.for_.dominant_color if isinstance(step.wait.for_, f.WaitForArgs) else step.wait.for_)
    elif isinstance(step.wait.for_, f.FindElement):
        for_find_element = step.wait.for_
    elif step.wait.for_:
        raise ValueError("Invalid value for field `wait.for`: ", step.wait.for_)

    with tempfile.TemporaryDirectory('miniqa-wait') as tempdir:
        while True:
            pth = os.path.join(tempdir, f"{time.time()}.ppm")
            img: numpy.ndarray | None = None  # the image is only loaded here if it provides a benefit; see below

            await worker.qmp.screendump(pth)

            is_done = False
            timeout_msg = "Wait timed out!"

            if for_dominant_color:
                is_done, timeout_msg = await _check_done_dominant_color(
                    pth=pth,
                    target_dominant_color=for_dominant_color,
                    max_color_diff=diff_threshold,
                    regions=regions,
                    ignore_regions=ignore_regions,
                )
            elif for_find_element:
                img = open_image(pth)  # load the image, so it's cached for the next comparison -> only load each image once
                with log_perf("_check_done_find_element"):
                    is_done, timeout_msg = await _check_done_find_element(
                        pth=pth,
                        current_img=img,
                        last_img=cached_last_img,
                        element_to_find=for_find_element,
                        regions=regions,
                        ignore_regions=ignore_regions,
                    )
            elif for_img:
                is_done, timeout_msg = await _check_done_image_match(
                    current_pth=pth,
                    target_img=for_img[1],
                    target_name=step.wait.for_,
                    max_diff=diff_threshold,
                    regions=regions,
                    ignore_regions=ignore_regions,
                )
            elif last_pth:
                img = open_image(pth)  # load the image, so it's cached for the next comparison -> only load each image once
                is_done, timeout_msg = await _check_done_image_change(
                    first_img=img,
                    second_img=cached_last_img,
                    first_pth=pth,
                    second_pth=last_pth,
                    min_diff=diff_threshold,
                    regions=regions,
                    ignore_regions=ignore_regions,
                )

            if is_done:
                break

            if time.monotonic() - start > f.to_seconds(step.wait.timeout):
                raise TestException.WaitTimedOut(
                    timeout_msg,
                    reference_image=for_img[0] if for_img else None,
                    reference_name=step.wait.for_ if for_img else None,
                    regions=regions,
                    ignore_regions=ignore_regions,
                )

            if last_pth:
                os.remove(last_pth)

            last_pth = pth
            cached_last_img = img

            await asyncio.sleep(check_interval)


async def _check_done_dominant_color(
        pth: str,
        target_dominant_color: tuple[int, int, int],
        max_color_diff: float,
        regions: list[f.ParsedRegion],
        ignore_regions: list[f.ParsedRegion],
) -> tuple[bool, str]:
    """
    Check if the dominant color of the image at [pth] is matching [target_dominant_color] with [diff_threshold].

    :return: (is_done, timeout_msg)
    """
    img_dom_col = await asyncio.to_thread(
        img_dominant_color,
        pth,
        regions,
        ignore_regions,
    )
    diff = color_diff(img_dom_col, target_dominant_color)

    logging.debug(f"[wait] waiting for dom. color {format_color(target_dominant_color)} color diff: {diff * 100:.2f} %,"
                  f" must be <= {max_color_diff * 100:.2f} %  (current color: {format_color(img_dom_col)})")

    is_done = diff <= max_color_diff

    timeout_msg = (f"Waiting for dominant color {format_color(target_dominant_color)} timed out (current color: "
                   f"{format_color(img_dom_col)}, diff: {diff * 100:.2f} %)!")

    return is_done, timeout_msg


async def _check_done_find_element(pth: str, current_img: numpy.ndarray | None, last_img: numpy.ndarray | None,
                                   element_to_find: FindElement, regions: list[f.ParsedRegion],
                                   ignore_regions: list[f.ParsedRegion]) -> tuple[bool, str]:
    """
    Check if the image at [pth] contains the element described by [element_to_find].

    :param current_img:
    :param last_img:
    :return: (is_done, timeout_msg)
    """

    timeout_msg = f"Waiting for element ({element_to_find.find}) timed out!"

    # If we have this and the last image at hand, first check if they differ with any significance,
    # so we can skip expensive OCR if the image did not change:
    if current_img is not None and last_img is not None:
        diff = await asyncio.to_thread(img_difference, current_img, last_img, regions, ignore_regions)
        if diff < 0.001:  # 0.1% tolerance
            logging.debug(f"Skipping OCR since image difference is {diff * 100:.2f} % (< 0.1 %)")
            return False, timeout_msg
    el = await find_element(
        pth,
        element_to_find.find.text,
        element_to_find.find.background_color,
        element_to_find.find.location_hint,
        regions,
        ignore_regions,
    )

    return el is not None, timeout_msg


async def _check_done_image_match(
        current_pth: str,
        target_img: numpy.ndarray | str,
        target_name: str,
        max_diff: float,
        regions: list[f.ParsedRegion],
        ignore_regions: list[f.ParsedRegion],
) -> tuple[bool, str]:
    """
    Check if the image at [current_pth] matches [target_img] with [max_diff].

    :return: (is_done, timeout_msg)
    """

    diff = await asyncio.to_thread(
        img_difference,
        current_pth,
        target_img,
        regions,
        ignore_regions,
    )

    logging.debug(f"[wait] img diff: {diff * 100:.2f} %, must be <= {max_diff * 100:.2f} % ({target_name} vs {current_pth})")
    timeout_msg = f"Waiting for {target_name} timed out (diff is {diff * 100:.2f} %, must be <= {max_diff * 100:.2f} %)!"

    return diff <= max_diff, timeout_msg


async def _check_done_image_change(
        first_img: numpy.ndarray | None,
        second_img: numpy.ndarray | None,
        first_pth: str,
        second_pth: Image | str,
        min_diff: float,
        regions: list[f.ParsedRegion],
        ignore_regions: list[f.ParsedRegion],
) -> tuple[bool, str]:
    """
    Check if the image at [first_pth] differs from [second_pth] by at least [min_diff].

    :return: (is_done, timeout_msg)
    """

    diff = await asyncio.to_thread(
        img_difference,
        first_img if first_img is not None else first_pth,
        second_img if second_img is not None else second_pth,
        regions,
        ignore_regions,
    )

    logging.debug(f"[wait] screen change: {diff * 100:.2f} %, must be >= {min_diff * 100:.2f} % ({first_pth} vs {second_pth})")
    timeout_msg = f"Waiting for screen change timed out (diff is {diff * 100:.2f} %, but must be >= {min_diff * 100:.2f} %)!"

    return diff >= min_diff, timeout_msg


# === Utilities ===

def _find_path(pth: str, likely_extension: str, likely_directory: str):
    res = f"{pth}.{likely_extension.lstrip(os.extsep)}" if not os.extsep in pth else pth
    if os.path.isfile(res): return res

    res = os.path.join(likely_directory, res)
    if os.path.isfile(res): return res

    return res
