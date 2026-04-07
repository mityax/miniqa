import asyncio
import logging
import os
import shutil
import time
from pathlib import Path

from miniqa.lib import snapshot_cache
from miniqa.lib.config import CONFIG, RUNTIME_TMPDIR
from miniqa.lib.runner.test_models import TestStatus, TestResult
from miniqa.lib.runner.test_runner import TestWorker, TestRunner
from miniqa.lib.test_case.test_case_file import TestCase
from miniqa.lib.test_case.test_case_utils import resolve_test_case_dependency_chain
from miniqa.lib.utils import slugify, load_tests
from miniqa.lib.webui.helpers import list_tests, try_parse_testcase
from miniqa.lib.webui.state import AppState, serialize_result


async def handle_websocket_message(msg: dict, state: AppState):
    """Route an incoming WS message to the appropriate handler."""
    handlers = {
        "getstate":          _handle_ws_getstate,
        "run_test":           _handle_ws_run_test,
        "cancel_edit_run":    _handle_ws_cancel_edit_run,
        "prepare_worker":     _handle_ws_prepare_worker,
        "cancel_prepare":     _handle_ws_cancel_prepare,
        "save_test":          _handle_ws_save_test,
        "add_test":           _handle_ws_add_test,
        "delete_test":        _handle_ws_delete_test,
        "run_pipeline":       _handle_ws_run_pipeline,
        "cancel_pipeline":    _handle_ws_cancel_pipeline,
        "create_screenshot":  _handle_ws_create_screenshot,
        "delete_screenshot":  _handle_ws_delete_screenshot,
        "replace_reference":  _handle_ws_replace_reference,
    }
    handler = handlers.get(msg.get("type"))
    if handler:
        await handler(msg.get("payload", {}), state)
    else:
        await state.send("error", {"message": f"Unknown message type: {msg.get('type')}"})


# ═══════════════════════════════════════════════════════════════════════════════
# Message Handlers
# ═══════════════════════════════════════════════════════════════════════════════

async def _handle_ws_getstate(_payload: dict, state: AppState):
    await state.send("state", state.full_snapshot())
    await state.send("tests", list_tests())


async def _handle_ws_run_test(payload: dict, state: AppState):
    """
    Run the current test on the edit-view worker.
    Expects: {stem, yaml}
    The worker must already be ready (snapshot loaded) before calling this.
    """

    stem: str = payload.get("stem", state.edit_test_stem or "")
    yaml_text: str = payload.get("yaml", state.edit_yaml or "")

    try:
        tc = TestCase.from_yaml_text(yaml_text, stem)
    except Exception as e:
        logging.exception("Unexpected error", exc_info=e, stack_info=True)
        await state.send("error", {"message": f"Invalid test: {e}"})
        return

    if state.edit_worker_preparation_task and not state.edit_worker_preparation_task.done():
        await state.send("error", {"message": "A run is already in progress."})
        return

    if state.edit_worker is None:
        await state.send("error", {"message": "Worker is not ready. Please prepare the VM first."})
        return

    def _status_change_cb(tc: TestCase, status: TestStatus, result: TestResult | None, current_step: int | None):
        if state.active_ws_queue:
            asyncio.get_event_loop().call_soon_threadsafe(
                state.active_ws_queue.put_nowait,
                {
                    "type": "edit_worker_update",
                    "message": None,
                    "payload": {
                        "status": "running" if not result else "ready",
                        "result": serialize_result(result) if result else None,
                        "current_step": current_step,
                    },
                },
            )
    async def _run():
        state.edit_worker_status = "running"
        state.edit_worker_message = None
        await state.send("edit_worker_update", {
            "status": "running", "message": None, "progress": None
        })
        try:
            result = await state.edit_worker.run_test(tc, status_change_callback=_status_change_cb)
            state.edit_worker_status = "ready"
            #await state.send("edit_worker_update", {
            #    "status": "ready",
            #    "run_result": serialize_result(result) if result else None,
            #    "message": None
            #})
        except asyncio.CancelledError:
            state.edit_worker_status = "ready"
            await state.send("edit_worker_update", {"status": "ready", "cancelled": True, "message": None})
        except Exception as e:
            logging.exception("Unexpected error", exc_info=e, stack_info=True)
            state.edit_worker_status = "error"
            state.edit_worker_message = str(e)
            await state.send("edit_worker_update", {"status": "error", "message": str(e)})


    state.edit_worker_preparation_task = asyncio.create_task(_run())


async def _handle_ws_cancel_edit_run(_payload: dict, state: AppState):
    if state.edit_worker_preparation_task and not state.edit_worker_preparation_task.done():
        state.edit_worker_preparation_task.cancel()


async def _handle_ws_prepare_worker(payload: dict, state: AppState):
    """
    Boot the edit worker and load the snapshot chain required for `stem`.
    Keeps the worker alive for subsequent runs.
    Expects: {stem}
    """

    stem: str = payload.get("stem", "")

    # all_test_dicts = list_tests()
    all_tcs = load_tests()
    target_tc = next((t for t in all_tcs if t.name == stem), None)

    if target_tc is None:
        await state.send("error", {"message": "Cannot prepare: invalid test."})
        return

    # Resolve snapshot dependency chain
    try:
        dependency_chain: list[TestCase] = resolve_test_case_dependency_chain(target_tc, all_tcs)
    except ValueError as e:
        logging.exception("Error while resolving snapshot dependency: ", exc_info=e, stack_info=True)
        state.edit_worker_status = "error"
        state.edit_worker_message = str(e)
        await state.send("edit_worker_update", {
            "status": "error", "message": str(e)
        })
        return

    if state.edit_worker_preparation_task and not state.edit_worker_preparation_task.done():
        state.edit_worker_preparation_task.cancel()

    async def _prepare():
        # Check if the right snapshot is already present:
        if (
            state.edit_worker is not None
            and state.edit_worker_status in ("runnning", "ready")
            and target_tc.from_ in state.edit_worker.snapshots
        ):
            await state.send("edit_worker_update", {"status": "loading_snapshot", "progress": None, "message": f"Loading snapshot {target_tc.from_}"})
            await state.edit_worker.load_snapshot(target_tc.from_)
            await state.send("edit_worker_update", {"status": "ready", "progress": None, "message": None})
            return

        # If no snapshot is required, the worker needs to be rebooted:
        if target_tc.from_ is None and state.edit_worker:
            # Stop edit worker for it to be rebooted below:
            await state.edit_worker.stop()
            state.edit_worker_status = "stopped"
            state.edit_worker = None

        # Boot worker if needed
        cached = False

        if state.edit_worker is None:
            state.edit_worker_status = "booting"
            await state.send("edit_worker_update", {"status": "booting", "progress": None, "message": None})
            worker = TestWorker()

            # If we have the required snapshot in cache, copy it in place before creating the worker:
            if target_tc.from_:
                checksum = snapshot_cache.checksum(dependency_chain)
                if snapshot_cache.snapshot_exists(target_tc.from_, checksum):
                    await snapshot_cache.clone_snapshot_to(worker.disks_dir, target_tc.from_, checksum)
                    cached = True

            try:
                await worker.start(enable_vnc=True, initial_snapshot=target_tc.from_ if cached else None)
            except Exception as e:
                logging.exception("Unexpected error", exc_info=e, stack_info=True)
                state.edit_worker_status = "error"
                state.edit_worker_message = f"VM boot failed: {e}"
                await state.send("edit_worker_update", {
                    "status": "error", "message": state.edit_worker_message
                })
                return

            state.edit_worker = worker

            # Start / restart NoVNC proxy for this worker
            port = await worker.query_vnc_port()
            if port is None:
                state.edit_worker_status = "error"
                state.edit_worker_message = f"VM VNC setup failed."
                await state.send("edit_worker_update", {
                    "status": "error", "message": "VM VNC setup failed. Shutting down VM."
                })
                await worker.stop()
                return
            await state.websockify_manager.start(
                host=state.novnc_host,
                listen_port=state.novnc_port,
                target_port=port,
            )

        if dependency_chain and not cached:
            async def _progress_update(cur_test_name: str, curr: int, total: int):
                state.edit_worker_progress = (curr, total)
                await state.send("edit_worker_update", {
                    "status": "loading_snapshot",
                    "progress": [curr, total],
                    "current_test": dep_tc.name,
                    "message": None,
                })

            state.edit_worker_status = "loading_snapshot"
            steps_to_run_total = sum(len(tc.steps) for tc in dependency_chain)

            for idx, dep_tc in enumerate(dependency_chain):
                steps_ran_so_far = sum(len(tc.steps) for tc in dependency_chain[:idx])

                await _progress_update(dep_tc.name, steps_ran_so_far, steps_to_run_total)

                try:
                    async with asyncio.TaskGroup() as task_group:
                        result = await state.edit_worker.run_test(
                            dep_tc,
                            status_change_callback=lambda tc, stat, res, curr_step: task_group.create_task(
                                _progress_update(tc.name, steps_ran_so_far + (curr_step or 0), steps_to_run_total),
                            )
                        )

                    if not result.success:
                        state.edit_worker_status = "error"
                        state.edit_worker_message = f"Failed to create snapshot via test '{dep_tc.name}': {result.message}"
                        await state.send("edit_worker_update", {
                            "status": "error",
                            "message": state.edit_worker_message,
                            "failed_result": serialize_result(result) if result else None,
                        })
                        logging.exception("Failed to create snapshot via test '{dep_tc.name}'", exc_info=True, stack_info=result.exception)
                        return
                except asyncio.CancelledError:
                    state.edit_worker_status = "stopped"
                    await state.edit_worker.stop()
                    await state.send("edit_worker_update", {"status": "stopped", "message": None, "cancelled": True})
                    return
                except Exception as e:
                    logging.exception("Unexpected error", exc_info=e, stack_info=True)
                    state.edit_worker_status = "error"
                    state.edit_worker_message = str(e)
                    await state.send("edit_worker_update", {
                        "status": "error", "message": str(e)
                    })
                    return

            await snapshot_cache.add_snapshot(
                [target_tc.from_],
                snapshot_cache.checksum(dependency_chain),
                state.edit_worker.disks_dir,
            )

        state.edit_worker_status = "ready"
        state.edit_worker_progress = None

        await state.send("edit_worker_update", {
            "status": "ready",
            "progress": None,
            "message": None,
        })

    state.edit_worker_preparation_task = asyncio.create_task(_prepare())


async def _handle_ws_cancel_prepare(_payload: dict, state: AppState):
    if state.edit_worker_preparation_task and not state.edit_worker_preparation_task.done():
        state.edit_worker_preparation_task.cancel()


async def _handle_ws_save_test(payload: dict, state: AppState):
    """Save the edited YAML to disk. Expects: {stem, yaml}"""

    stem: str = payload.get("stem", "").strip()
    yaml_text: str = payload.get("yaml")

    if not stem or yaml_text is None:
        await state.send("error", {"message": "Invalid request. `stem` and `yaml_text` are required."})
        return

    # Validate before saving
    try:
        TestCase.from_yaml_text(yaml_text, stem)
    except Exception as e:
        await state.send("error", {"message": f"YAML validation failed: {repr(e)}"})

    # Find the file
    test_dir = Path(CONFIG.tests_directory)
    if not (target_fn := test_dir / f"{stem}.yaml").is_file():
        target_fn = test_dir / f"{stem}.yml"

    target_fn.write_text(yaml_text)
    state.edit_yaml = yaml_text
    state.edit_has_unsaved = False

    await state.send("saved", {"stem": stem})
    await state.send("tests", list_tests())


async def _handle_ws_add_test(payload: dict, state: AppState):
    """Create a new test file. Expects: {filename, yaml}"""

    filename: str = payload.get("filename", "")
    yaml_text: str = payload.get("yaml", "")

    if not filename.endswith((".yml", ".yaml")):
        filename += ".yml"

    target = Path(CONFIG.tests_directory) / filename

    if target.exists():
        await state.send("error", {"message": f"File '{filename}' already exists."})
        return

    target.write_text(yaml_text)
    await state.send("tests", list_tests())


async def _handle_ws_delete_test(payload: dict, state: AppState):
    """Delete a test file. Expects: {stem}"""

    stem: str = payload.get("stem", "")

    tests_dir = Path(CONFIG.tests_directory)

    (tests_dir / f"{stem}.yml").unlink(missing_ok=True)
    (tests_dir / f"{stem}.yaml").unlink(missing_ok=True)

    await state.send("tests", list_tests())


async def _handle_ws_run_pipeline(payload: dict, state: AppState):
    """
    Run all or a subset of tests through TestRunner.
    Expects: {stems?: string[]}  — if omitted, run all.
    """

    if state.pipeline_running:
        await state.send("error", {"message": "Pipeline is already running."})
        return

    all_test_dicts = list_tests()
    all_tcs = {
        d["stem"]: tc
        for d in all_test_dicts
        if (tc := try_parse_testcase(d["yaml"], d["stem"])) is not None
    }

    requested_stems: list[str] | None = payload.get("stems")

    if requested_stems is not None:
        # Expand with dependency chain:
        stems_to_run: list[str] = []

        for req_stem in requested_stems:
            tc = all_tcs.get(req_stem)

            if tc is None:
                await state.send("error", {"message": f"Test {req_stem} not found or invalid."})
                return

            try:
                chain = resolve_test_case_dependency_chain(tc, list(all_tcs.values()))
            except ValueError as e:
                logging.exception("Error while resolving snapshot dependency", exc_info=e, stack_info=True)
                await state.send("error", {"message": str(e)})
                return


            if req_stem not in stems_to_run:
                stems_to_run.append(req_stem)

            # If no up-to-date snapshot for this TestCase exists, queue its dependencies too:
            if tc.from_ and not snapshot_cache.snapshot_exists(tc.from_, snapshot_cache.checksum(chain)):
                for i, dep in enumerate(chain):
                    # If an up-to-date snapshot for this dependency exists, skip further dependencies:
                    if dep.from_ and snapshot_cache.snapshot_exists(dep.from_, snapshot_cache.checksum(chain[i + 1:])):
                        break

                    dep_stem = next((stem for stem, t in all_tcs.items() if t is dep))
                    if dep_stem not in stems_to_run:
                        stems_to_run.append(dep_stem)

        tcs_to_run = [all_tcs[s] for s in stems_to_run]
    else:
        stems_to_run = list(all_tcs.keys())
        tcs_to_run = list(all_tcs.values())

    # Reset/initialize the affected state:
    state.test_statuses = {s: "queued" for s in stems_to_run}
    state.test_results = {}
    state.test_current_steps = {}
    state.test_start_time = {}
    state.pipeline_running = True
    await state.send("state", state.full_snapshot())

    # Build a name -> stem mapping for the status callback:
    name_to_stem: dict[str, str] = {
        tc.name: stem
        for stem, tc in all_tcs.items()
    }

    def _on_status_changed(tc: TestCase, status: TestStatus, result: TestResult, current_step: int | None = None):
        """Callback invoked by TestRunner for each status change of a test/test step."""

        stem = name_to_stem[tc.name]

        state.test_statuses[stem] = status
        state.test_results[stem] = result
        state.test_current_steps[stem] = current_step
        state.test_start_time[stem] = time.time()

        if state.active_ws_queue:
            asyncio.get_event_loop().call_soon_threadsafe(
                state.active_ws_queue.put_nowait,
                {
                    "type": "test_status",
                    "payload": {
                        "stem": stem,
                        "status": status,
                        "result": serialize_result(result) if result else None,
                        "current_step": current_step,
                    },
                },
            )

    async def _run_pipeline():
        runner = TestRunner(tcs_to_run, on_test_status_changed=_on_status_changed, workers=state.pipeline_max_jobs)
        state.pipeline_runner = runner

        try:
            await runner.run()
        except asyncio.CancelledError:
            await state.send("pipeline_done", {"message": f"Pipeline canceled."})
        except Exception as e:
            if isinstance(e, ExceptionGroup) and len(e.exceptions) == 1:
                e = e.exceptions[0]
            logging.exception(str(e), exc_info=e, stack_info=True)
            await state.send("error", {"message": f"Pipeline error: {e}"})
        finally:
            state.pipeline_running = False
            state.pipeline_runner = None
            await state.send("pipeline_done", {})

    state.pipeline_task = asyncio.create_task(_run_pipeline())


async def _handle_ws_cancel_pipeline(_payload: dict, state: AppState):
    """Cancel the running pipeline"""

    if state.pipeline_task and not state.pipeline_task.done():
        state.pipeline_task.cancel()


async def _handle_ws_create_screenshot(payload: dict, state: AppState):
    """
    Capture a screendump from the edit worker's QMP interface.
    Expects: {name}  — the desired name (without extension).
    """

    name: str = payload.get("name", "screenshot")

    if state.edit_worker is None:
        await state.send("error", {"message": "VM is not running."})
        return

    tmp = Path(RUNTIME_TMPDIR) / f"webui-screendump-{slugify(name)}.ppm"

    try:
        await state.edit_worker.qmp.screendump(str(tmp))
        dest = Path(CONFIG.refs_directory) / f"{name}.ppm"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), dest)
        await state.send("screenshot_created", {"name": name})
    except Exception as e:
        logging.exception("Unexpected error", exc_info=e, stack_info=True)
        await state.send("error", {"message": f"Screenshot failed: {e}"})
    finally:
        tmp.unlink(missing_ok=True)


async def _handle_ws_delete_screenshot(payload: dict, state: AppState):
    """Delete a reference screenshot. Expects: {path}  (relative to refs_path)."""

    rel: str = payload.get("path", "")
    full = Path(CONFIG.refs_directory) / rel

    if not full.resolve().is_relative_to(Path(CONFIG.refs_directory).resolve()):
        await state.send("error", {"message": "Invalid path."})
        return

    full.unlink(missing_ok=True)

    await state.send("screenshots_updated", {})


async def _handle_ws_replace_reference(payload: dict, state: AppState):
    """
    Replace a reference screenshot with the 'actual' screenshot from a failed step.
    Expects: {actual_path, ref_name}
    """

    actual_path: str = payload.get("actual_path", "")
    ref_name: str = payload.get("ref_name", "")

    src = Path(actual_path)
    dest = Path(CONFIG.refs_directory) / f"{ref_name}.ppm"
    
    if not src.exists():
        await state.send("error", {"message": f"Screenshot to replace reference not found: {actual_path}"})
        return

    if not dest.exists():
        await state.send("error", {"message": f"Reference screenshot to be replaced not found: {ref_name} – file does not exist at {dest}"})
        return

    shutil.copy(str(src), dest)
    
    await state.send("reference_replaced", {"ref_name": ref_name})
