#!/usr/bin/env python3

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from collections import defaultdict

import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm


# --------------------------------------------------------
# main
# --------------------------------------------------------

async def cli():
    asyncio.get_running_loop().set_exception_handler(_exception_handler)

    ap = argparse.ArgumentParser()

    ap.add_argument("-w", "--workers", type=int, default=1)
    ap.add_argument("-v", "--verbose", action="count")

    sub = ap.add_subparsers(dest="cmd", required=True)

    setup = sub.add_parser("setup")
    setup.add_argument("--ocr", action="store_true")
    setup.add_argument("--webui", action="store_true")

    prepare = sub.add_parser("prepare-image")
    prepare.add_argument("image")

    run = sub.add_parser("run")
    run.add_argument("selected", nargs="*")

    webui = sub.add_parser("editor")
    webui.add_argument("--setup", action="store_true")

    tinker = sub.add_parser("tinker")
    tinker.add_argument("--qmp", action="store_true")

    args = ap.parse_args()

    if args.verbose:
        level = logging.DEBUG if args.verbose > 1 else logging.INFO
        os.environ["MINIQA_LOGLEVEL"] = logging.getLevelName(level)
        logging.basicConfig(level=level, force=True)  # use `force` to overwrite existing config (the commandline args take precedence over the env var)

    match args.cmd:
        case "setup":
            if not args.ocr and not args.webui:
                args.ocr = args.webui = True
            if args.ocr:
                # The module prompts to download on import automatically, if OCR is supported
                from miniqa.lib.image_analysis import find_element  # noqa
            if args.webui:
                from miniqa.lib.webui.setup import setup_dependencies
                setup_dependencies()
            print("Everything set up.")
        case "run":
            await run_tests(selected_tests=args.selected, workers=args.workers)
        case "prepare-image":
            await prepare_img(args.image)
        case "editor":
            from miniqa.lib.webui.app import run_webui
            from miniqa.lib.config import CONFIG
            await run_webui(CONFIG.tests_directory, pipeline_max_workers=args.workers)
        case "tinker":
            await boot_for_manual_tinkering(enable_qmp=args.qmp)


async def run_tests(selected_tests: list[str], workers: int = 1):
    from miniqa.lib.utils import load_tests
    from miniqa.lib.test_case.test_case_file import TestCase
    from miniqa.lib.runner.test_models import TestStatus
    from miniqa.lib.utils import std_out_err_redirect_tqdm
    from miniqa.lib.runner.test_runner import TestRunner

    tests = load_tests()

    if selected_tests:
        tests = [t for t in tests if t.name in selected_tests]

    steps_so_far = defaultdict(int)

    def prog_cb(tc: TestCase, status: TestStatus, curr_step: int | None, pbar: tqdm.tqdm | None):
        if not pbar:
            return

        steps_so_far[tc.name] = max(steps_so_far[tc.name], curr_step or 0) if status in ('queued', 'started') else len(tc.steps)
        pbar.update(sum(steps_so_far.values()) - pbar.n)
        pbar.set_description(f"Running test {len(steps_so_far)} / {len(tests)} ({len(runner.failed_tests)} failed)")

    print(f"Running {len(tests)} test(s).")

    if sys.stdout.isatty():
        with std_out_err_redirect_tqdm() as orig_stdout, logging_redirect_tqdm():
            with tqdm.tqdm(total=sum(len(tc.steps) for tc in tests), file=orig_stdout, unit="step") as pbar:
                runner = TestRunner(tests, workers,
                                    on_test_status_changed=lambda tc, stat, res, curr: prog_cb(tc, stat, curr, pbar))
                await runner.run(print_summary=False)
    else:
        runner = TestRunner(tests, workers,
                            on_test_status_changed=lambda tc, stat, res, curr: prog_cb(tc, stat, curr, None))
        await runner.run(print_summary=False)

    runner.print_summary()

    if runner.failed_tests:
        raise SystemExit(1)

    fail_when_not_ran = os.environ.get("MINIQA_FAIL_WHEN_NOT_RAN", "0").lower() in ('1', 'true', 'yes')
    if fail_when_not_ran and runner.unrunnable_tests or runner.remaining_tests:
        raise SystemExit(1)


async def prepare_img(image_file: str):
    from miniqa.lib.qemu import QEMUWorker
    from miniqa.lib.config import CONFIG
    from miniqa.lib.qemu import detect_disk_image_format, convert_raw_image_to_qcow2

    if await detect_disk_image_format(image_file) == 'raw':
        qcow2_image_file = os.path.splitext(image_file)[0] + os.path.extsep + 'qcow2'
        print(f" - Converting raw image to qcow2 image at {qcow2_image_file} for snapshotting support... ", end="", flush=True)
        await convert_raw_image_to_qcow2(image_file, qcow2_image_file)
        image_file = qcow2_image_file
        print("done")
        print()

    CONFIG.image = image_file
    CONFIG.initial_snapshot = None
    CONFIG.headless = False

    print('Please enter a snapshot tag of your choice (e.g. "base" or "manually-prepared-vm"). Make sure to use lower-camel-case or snake_case as per your preference.')
    snapshot_tag = input('Your snapshot name [default: base]: ').strip() or 'base'

    if not re.match(r"[-\w]+$", snapshot_tag):
        raise ValueError("Invalid snapshot tag: ", snapshot_tag)
    print()

    print(" - Booting VM for manual initialization process...")
    worker = QEMUWorker(use_overlay=False)
    await worker.start()

    print()
    print('Now, prepare the VM as needed. When you\'re done, return to this terminal and press return to create '
          'the snapshot.')
    input("Press return to snapshot... ")
    print()

    print(f' - Creating snapshot "{snapshot_tag}"... ', end="", flush=True)
    await worker.save_snapshot(snapshot_tag)
    print("done")

    print(" - Stopping VM...", end="", flush=True)
    await worker.stop()
    print("done")

    print(" - Extracting new image from snapshot... ", end="", flush=True)
    snapshot_image_file = os.path.splitext(image_file)[0] + '-' + snapshot_tag + os.path.splitext(image_file)[1]
    subprocess.run(['qemu-img', 'convert', '-O', 'qcow2', '--snapshot', snapshot_tag, image_file, snapshot_image_file], check=True)
    print("done")

    print()
    print("All done. Use the following configuration in your miniqa.yml to always boot test workers from the "
          "snapshot you created just now:")
    print()
    print(f"image: {snapshot_image_file}")


async def boot_for_manual_tinkering(enable_qmp: bool = False):
    from miniqa.lib.config import CONFIG
    from miniqa.lib.qemu import QEMUWorker
    from miniqa.lib.qemu.qmp import QMPError

    CONFIG.headless = False

    if not enable_qmp:
        CONFIG.qemu_args.extend(('-monitor', 'stdio'))

    print(" - Booting VM for manual tinkering...")

    worker = QEMUWorker()
    await worker.start(stdout=None, stderr=None)

    if enable_qmp:
        while True:
            qmp = await asyncio.to_thread(input, "(qmp) ")
            try:
                parsed = json.loads(qmp.strip())
            except ValueError:
                print("Invalid JSON; can't send.")
                continue
            try:
                res = await worker.qmp.send_raw(parsed)
                print(f" <- {json.dumps(res)}")
            except QMPError as e:
                print("Error while trying to run QMP command: ", e)
    else:
        await worker.wait_exit()


def _exception_handler(loop: asyncio.AbstractEventLoop, context: dict):
    loop.stop()

    if 'exception' in context:
        raise context['exception']
    raise SystemExit(1)


def main():
    try:
        asyncio.run(cli())
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        if 'Event loop stopped before Future completed' in repr(e):
            return 1
        else:
            raise

    return 0


if __name__ == "__main__":
    sys.exit(main())

