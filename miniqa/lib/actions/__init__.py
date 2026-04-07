import asyncio
import logging
import os
from typing import Literal, Any

from .wait_action import run_wait_step as _run_wait_step
from ..config import CONFIG
from ..errors import TestException
from ..image_analysis.compare import img_difference
from ..image_analysis.find_element import find_element
from ..qemu import QEMUWorker
from ..qemu.qemu_coordinates import position_to_coordinates
from ..qemu.qemu_keymap import string_to_qemu_key_invocations
from ..test_case import test_case_file as f


async def run_action(worker: QEMUWorker, step: f.Step, test_case: f.TestCase | None = None):
    match step:
        case f.SleepStep():
            await asyncio.sleep(f.to_seconds(step.sleep))

        case f.MouseMoveStep():
            x, y = await position_to_coordinates(worker, step.mouse_move, translate_to_input_coordinates=True)
            await worker.qmp.input(_mouse_motion_event(x, y))

        case f.MousePressStep():
            args = f.MouseButtonArgs.create_from(step.mouse_press)
            if args.position:
                await run_action(worker, f.MouseMoveStep(mouse_move=args.position), test_case)
            await worker.qmp.input(_mouse_button_event(args.button, True))

        case f.MouseReleaseStep():
            args = f.MouseButtonArgs.create_from(step.mouse_release)
            if args.position:
                await run_action(worker, f.MouseMoveStep(mouse_move=args.position), test_case)
            await worker.qmp.input(_mouse_button_event(args.button, False))

        case f.ClickStep():
            args = f.MouseButtonArgs.create_from(step.click)
            if args.position:
                await run_action(worker, f.MouseMoveStep(mouse_move=args.position), test_case)
            await worker.qmp.input(_mouse_button_event(args.button, True))
            await worker.qmp.input(_mouse_button_event(args.button, False))

        case f.KeyPressStep():
            await worker.qmp.input(_key_event(step.key_press, True))

        case f.KeyReleaseStep():
            await worker.qmp.input(_key_event(step.key_release, False))

        case f.InvokeKeyStep():
            await worker.qmp.input(_key_event(step.invoke_key, True))
            await worker.qmp.input(_key_event(step.invoke_key, False))

        case f.InvokeKeysStep():
            await _step_invoke_keys(step, worker)

        case f.TypeTextStep():
            await _step_type_text(step, worker)

        case f.TouchPressStep():
            args = f.TouchArgs.create_from(step.touch_press)
            x, y = await position_to_coordinates(worker, args.position, translate_to_input_coordinates=True)
            await worker.qmp.input(_touch_event('begin', x, y, args.slot))

        case f.TouchMoveStep():
            args = f.TouchArgs.create_from(step.touch_move)
            x, y = await position_to_coordinates(worker, args.position, translate_to_input_coordinates=True)
            await worker.qmp.input(_touch_event('update', x, y, args.slot))

        case f.TouchReleaseStep():
            args = f.TouchArgs.create_from(step.touch_release)
            x, y = await position_to_coordinates(worker, args.position, translate_to_input_coordinates=True)
            await worker.qmp.input(_touch_event('end', x, y, args.slot))

        case f.TouchStep():
            await _run_touch_step(step, worker)

        case f.ScreenshotStep():
            await _run_screenshot_step(step, worker)

        case f.SnapshotStep():
            await worker.save_snapshot(step.snapshot)

        case f.WaitStep():
            await _run_wait_step(step, worker)

        case f.AssertStep():
            if not await find_element(step.assert_.find.text, step.assert_.find.background_color, step.assert_.find.location_hint):
                raise TestException.PositionNotFound(f"Could not find element: {step.assert_.find}")

        case f.CustomStep():
            await _run_custom_step(step, worker, test_case)

        case _:
            raise ValueError("Invalid action type: ", step)


# --------------------------------------------------------
# Input event generators
# --------------------------------------------------------

def _key_event(key: str | int, down: bool = True):
    return [{
        "type": "key",
        "data": {
            "down": down,
            "key": {"type": "qcode", "data": key} if isinstance(key, str) else {"type": "number", "data": key}
        }
    }]


def _mouse_motion_event(x, y):
    return [{
        "type": "abs",
        "data": {"axis": "x", "value": x}
    },{
        "type": "abs",
        "data": {"axis": "y", "value": y}
    }]


def _mouse_button_event(button, down=True):
    return [{
        "type": "btn",
        "data": {"down": down, "button": button}
    }]

def _touch_event(
    type_: Literal["begin", "update", "end"],
    x: int,
    y: int,
    slot: int = 0,
    tracking_id: int | None = None,
) -> list[dict[str, Any]]:
    if type_ =="end":
        tracking_id = -1
    elif tracking_id is None:
        tracking_id = slot

    mtt = {"slot": slot, "tracking-id": tracking_id, "axis": "x", "value": 0}

    if type_ == "end":
        return [{"type": "mtt", "data": {"type": "end", **mtt}}]

    return [
        {"type": "mtt", "data": {"type": type_, **mtt}},
        {"type": "btn", "data": {"button": "touch", "down": True}},
        {"type": "mtt", "data": {"type": "data", **mtt, "axis": "x", "value": x}},
        {"type": "mtt", "data": {"type": "data", **mtt, "axis": "y", "value": y}},
    ]


# --------------------------------------------------------
# Complex Actions
# --------------------------------------------------------

async def _step_invoke_keys(step: f.InvokeKeysStep, worker: QEMUWorker):
    if step.sequential:
        for key in step.invoke_keys:
            await asyncio.sleep(0.03 / f.to_speed_factor(step.speed))
            await worker.qmp.input(_key_event(key, True))
            await asyncio.sleep(0.03 / f.to_speed_factor(step.speed))
            await worker.qmp.input(_key_event(key, False))
    else:
        for key in step.invoke_keys:
            await worker.qmp.input(_key_event(key, True))
            await asyncio.sleep(0.03 / f.to_speed_factor(step.speed))
        for key in reversed(step.invoke_keys):
            await asyncio.sleep(0.03 / f.to_speed_factor(step.speed))
            await worker.qmp.input(_key_event(key, False))


async def _step_type_text(step: f.TypeTextStep, worker: QEMUWorker):
    invocations = string_to_qemu_key_invocations(step.type_text)

    for ev_type, key_code in invocations:
        await asyncio.sleep(0.03 / f.to_speed_factor(step.speed))
        await worker.qmp.input(_key_event(key_code, ev_type == "down"))


async def _run_touch_step(step: f.TouchStep, worker: QEMUWorker):
    items = step.touch if isinstance(step.touch, list) else [step.touch]

    for i, item in enumerate(items):
        pos = item.position if isinstance(item, f.TouchArgs) else item
        slot = item.slot if isinstance(item, f.TouchArgs) else 45
        translated_x, translated_y = await position_to_coordinates(worker, pos, translate_to_input_coordinates=True)

        if i == 0:
            await worker.qmp.input(_touch_event('begin', translated_x, translated_y, slot, tracking_id=slot))

        if 0 < i < len(items):
            await worker.qmp.input(_touch_event('update', translated_x, translated_y, slot, tracking_id=slot))

        if i == len(items) - 1:
            await worker.qmp.input(_touch_event('end', translated_x, translated_y, slot, tracking_id=-1))

        await asyncio.sleep(0.05 / f.to_speed_factor(step.speed))


async def _run_screenshot_step(step: f.ScreenshotStep, worker: QEMUWorker):
    fname = f"{step.screenshot.name}.ppm"
    out_img = os.path.join(CONFIG.out_directory, fname)
    ref_img = os.path.join(CONFIG.refs_directory, fname)

    os.makedirs(os.path.dirname(out_img), exist_ok=True)

    await worker.qmp.screendump(out_img)

    if os.path.exists(ref_img):
        diff = await asyncio.to_thread(
            img_difference,
            out_img,
            ref_img,
            f.to_parsed_regions(step.screenshot.regions),
            f.to_parsed_regions(CONFIG.ignore_regions),
        )
        if diff > f.to_ratio(step.screenshot.max_diff):
            raise TestException.ImageMismatch(
                f"Image mismatch (diff: {diff * 100:.2f} %)",
                reference_name=step.screenshot.name,
                reference_image=ref_img,
                actual_image=out_img,
                regions=f.to_parsed_regions(step.screenshot.regions),
                ignore_regions=f.to_parsed_regions(CONFIG.ignore_regions),
            )
    else:
        logging.info(f"Created baseline screenshot `{fname}`")
        os.makedirs(os.path.dirname(ref_img), exist_ok=True)
        os.rename(out_img, ref_img)


async def _run_custom_step(step: f.CustomStep, worker: QEMUWorker, test_case: f.TestCase):
    keys = set(step.model_extra.keys()) - set(f.CustomStep.model_fields.keys())  # exclude default step keys

    if len(keys) != 1:  # exclude default steps
        print(step.model_dump().keys())
        raise ValueError("A custom step call step must be unambiguous; it must contain a single key (the step name), "
                         f"but got: {tuple(keys)}")

    fn_name = keys.pop()
    del keys

    if test_case.defs is None or not fn_name in test_case.defs:
        raise ValueError(f"Custom step `{fn_name}` not defined in `defs`")

    steps = test_case.defs[fn_name]

    for i, step in enumerate(steps):
        logging.info(f"[Worker {worker.wid}]: Running {step.__class__.__name__}({step}) (substep #{i+1} of custom step {fn_name})")
        await run_action(worker, step, test_case)
