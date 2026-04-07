import os
import time

from . import QEMUWorker
from ..config import RUNTIME_TMPDIR, CONFIG
from ..errors import TestException
from ..image_analysis.find_element import find_element
from ..test_case import test_case_file as f
from ..test_case.test_case_file import to_parsed_regions

# QEMU uses 32768 steps (0 to 32767):
QEMU_INPUT_COORDINATE_RESOLUTION = 0x7FFF


async def position_to_coordinates(worker: QEMUWorker, position: f.AnyPosition,
                                  translate_to_input_coordinates: bool = False) -> tuple[int, int]:
    if isinstance(position, f.FindElement):
        fname = os.path.join(RUNTIME_TMPDIR, f'position-to-coordinates-{time.time()}.ppm')

        await worker.qmp.screendump(fname)

        element = await find_element(
            fname,
            position.find.text,
            position.find.background_color,
            position.find.location_hint,
            ignore_regions=to_parsed_regions(CONFIG.ignore_regions),
        )

        os.remove(fname)

        if not element:
            raise TestException.PositionNotFound(f"Could not find element: {position.find}")
        else:
            x, y, w, h = element
            res = (round(x+w/2), round(y+h/2))
    else:
        coords = f.to_parsed_position(position)
        values = [coords[0].value, coords[1].value]

        if all(coord.is_relative for coord in coords):  # shortcut: in this (common) case, we can skip screen size querying
            return (
                coords[0].to_abs(QEMU_INPUT_COORDINATE_RESOLUTION),
                coords[1].to_abs(QEMU_INPUT_COORDINATE_RESOLUTION),
            )

        if any(coord.is_relative or coord.value < 0 for coord in coords):
            w, h = await worker.qmp.screen_size
            values[0] = coords[0].to_abs(w)
            values[1] = coords[1].to_abs(h)

        res = (round(values[0]), round(values[1]))

    if translate_to_input_coordinates:
        w, h = await worker.qmp.screen_size
        res = (
            int((res.x / w) * QEMU_INPUT_COORDINATE_RESOLUTION),
            int((res.y / h) * QEMU_INPUT_COORDINATE_RESOLUTION),
        )

    return res
