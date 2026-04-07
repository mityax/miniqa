import asyncio
import logging
import os.path
import time
from asyncio import TaskGroup
from typing import Callable

from miniqa.lib import snapshot_cache
from miniqa.lib.actions import run_action
from miniqa.lib.assets_server import request_asset_server, unrequest_asset_server, floating_assets
from miniqa.lib.config import RUNTIME_TMPDIR
from miniqa.lib.errors import TestException
from miniqa.lib.qemu import QEMUWorker
from miniqa.lib.qemu.qmp import QMPError
from miniqa.lib.runner.test_models import TestStepResult, TestStatusChangeCallback, TestScreenshot, TestResult
from miniqa.lib.test_case.test_case_file import TestCase, Step
from miniqa.lib.test_case.test_case_utils import resolve_test_case_dependency_chain
from miniqa.lib.utils import slugify, ANSIColor, load_tests, print_markup


class TestRunner:
    def __init__(self,
                 tests: list[TestCase],
                 workers: int = 1,
                 on_test_status_changed: 'TestStatusChangeCallback | None' = None):
        self.tests = tests
        self.n_workers = workers
        self.workers = []
        self.test_status_changed_callback = on_test_status_changed

        self.all_tests = load_tests()
        self.all_queued_tests = list(tests)
        self.remaining_tests = list(self.tests)
        self.succeeded_tests = []   # tests that successfully completed
        self.failed_tests    = []   # tests that failed
        self.unrunnable_tests = []  # tests that cannot be run since a dependency failed to run
        self.test_results: dict[TestCase, TestResult] = {}

        self.__worker_done_event = asyncio.Event()
        self.__worker_exit_event = asyncio.Event()

        self.__used_mark = False
        self.duration: float | None = None

    async def run(self, print_summary: bool = True):
        assert not self.__used_mark, "TestRunner.run() cannot be called twice; Create a new TestRunner to run tests again."
        self.__used_mark = True

        start = time.monotonic()

        try:
            await asyncio.gather(
                self.__mainloop(),
                self.__raise_on_worker_exit()
            )
        except* _TestRunnerDone:
            pass
        finally:
            self.duration = time.monotonic() - start
            await self.__stop_all_workers()
            if print_summary:
                self.print_summary()

    def print_summary(self):
        print()
        for test in self.all_queued_tests:
            if test in self.unrunnable_tests:
                print_markup(
                    f"{ANSIColor.WARNING} • {ANSIColor.BOLD}{test.name}{ANSIColor.END}{ANSIColor.WARNING} "
                    f"could not be ran (unmet dependency).{ANSIColor.END}")
                continue
            elif test in self.remaining_tests:
                print_markup(
                    f"{ANSIColor.WARNING} • {ANSIColor.BOLD}{test.name}{ANSIColor.END}{ANSIColor.WARNING} "
                    f"has not been ran (due to early exit).{ANSIColor.END}")
                continue

            result = self.test_results.get(test)

            if not result:
                print_markup(
                    f"{ANSIColor.WARNING} • {ANSIColor.BOLD}{test.name}{ANSIColor.END}{ANSIColor.WARNING} "
                    f"could not be completed (due to early exit).{ANSIColor.END}")
                continue
            elif test in self.succeeded_tests:
                print_markup(
                    f"{ANSIColor.OKGREEN} ✔ {ANSIColor.BOLD}{test.name}{ANSIColor.END}{ANSIColor.OKGREEN} "
                    f"passed, took {result.duration:.2f}s.{ANSIColor.END}")
            else:
                print_markup(
                    f"{ANSIColor.FAIL} ✘ {ANSIColor.BOLD}{test.name}{ANSIColor.END}{ANSIColor.FAIL} failed "
                    f"at step #{result.failed_step_index + 1} "
                    f"({test.steps[result.failed_step_index].__class__.__name__}), took {result.duration:.2f}s:")
                print_markup(f"   → {result.exception.__class__.__name__}: {result.exception}{ANSIColor.END}")

        print()

        if self.failed_tests and len(self.test_results) == len(self.all_queued_tests):
            print_markup(
                f"{ANSIColor.BOLD}{ANSIColor.FAIL}✘ {len(self.failed_tests)} / {len(self.all_queued_tests)} test(s) "
                f"failed (took {self.duration:.1f}s).{ANSIColor.END}")
        elif self.failed_tests and len(self.test_results) < len(self.all_queued_tests):
            print_markup(
                f"{ANSIColor.BOLD}{ANSIColor.FAIL}✘ {len(self.failed_tests)} / {len(self.all_queued_tests)} test(s) "
                f"failed (took {self.duration:.1f}s), {len(self.all_queued_tests) - len(self.test_results)} could not "
                f"be ran.{ANSIColor.END}")
        elif len(self.test_results) < len(self.all_queued_tests):
            print_markup(
                f"⚠️ {ANSIColor.BOLD}{ANSIColor.WARNING} {len(self.all_queued_tests) - len(self.test_results)} "
                f"/ {len(self.all_queued_tests)} test(s) could not be ran, none failed (took {self.duration:.1f}s)."
                f"{ANSIColor.END}")
        else:
            print_markup(
                f"{ANSIColor.BOLD}{ANSIColor.OKGREEN}✔ All {len(self.all_queued_tests)} test(s) passed in "
                f"{self.duration:.1f}s.{ANSIColor.END}")


    async def __mainloop(self):
        async with asyncio.TaskGroup() as task_group:
            # Mainloop:
            while self.remaining_tests:
                # Distribute tasks to all existing free workers:
                await self.__distribute_tasks(task_group)

                # Create new workers, if there's capacity and tasks left:
                await self.__maybe_create_workers(task_group)
                self.__worker_done_event.clear()

                # Wait until a worker is ready:
                await self.__worker_done_event.wait()

                # Prune any worker no longer needed:
                await self.__prune_unusable_workers(task_group)

            # Wait until all dangling tests are finished:
            while any(w.is_busy for w in self.workers):
                await self.__worker_done_event.wait()
                self.__worker_done_event.clear()

            # Cancel task group explicitly to finish all background tasks:
            raise _TestRunnerDone()

    async def __distribute_tasks(self, task_group: TaskGroup):
        for worker in self.workers:
            if not worker.is_busy:
                tests = [t for t in self.remaining_tests if t.from_ in worker.snapshots or t.from_ is None]
                if tests:
                    self.remaining_tests.remove(tests[0])
                    print(f"[TestRunner] Assigning test \"{tests[0].name}\" to worker #{worker.wid} "
                          f"(current worker count: {len(self.workers)})")
                    task_group.create_task(self.__run_test_on_worker(worker, tests[0]))

    async def __maybe_create_workers(self, task_group: TaskGroup):
        allocatable_tests = list(self.remaining_tests)

        while len(self.workers) < self.n_workers:
            created_worker = False

            for test in tuple(allocatable_tests):
                dep_chain = resolve_test_case_dependency_chain(test, self.all_tests)
                checksum = snapshot_cache.checksum(dep_chain)

                logging.debug(f"[TestRunner] Checking snapshot {test.from_} (checksum: {checksum})")

                if not dep_chain or snapshot_cache.snapshot_exists(test.from_, checksum):
                    new_worker = TestWorker()
                    print(f"[TestRunner] Created worker #{new_worker.wid}")

                    if test.from_:
                        logging.debug(f"[TestRunner] Cloned cached snapshot {test.from_} to {new_worker.overlay}")
                        await snapshot_cache.clone_snapshot_to(new_worker.disks_dir, test.from_, checksum)

                    self.workers.append(new_worker)
                    task_group.create_task(self.__boot_worker(task_group, new_worker, test.from_))

                    created_worker = True
                    allocatable_tests.remove(test)
                    break

            if not created_worker:  # if no worker has been created, that's all we can do right now
                break

    async def __cache_snapshots(self, test: TestCase, worker: TestWorker):
        if test.snapshots:
            checksum = snapshot_cache.checksum([
                *resolve_test_case_dependency_chain(test, self.all_tests),
                test
            ])
            logging.debug(f"[TestRunner] Caching snapshots {test.snapshots} from {worker.overlay}")
            await snapshot_cache.add_snapshot(test.snapshots, checksum, worker.disks_dir)

    async def __prune_unusable_workers(self, task_group: TaskGroup):
        for worker in list(self.workers):
            is_usable = any(t.from_ in worker.snapshots or not t.from_ for t in self.remaining_tests)

            if (not worker.is_busy) and (not is_usable):
                print(f"[TestRunner] Shutting down no longer needed worker #{worker.wid}...")
                self.workers.remove(worker)
                await worker.destroy()

    async def __run_test_on_worker(self, worker: TestWorker, test: TestCase):
        try:
            res = await worker.run_test(test, self.test_status_changed_callback)
            if res.success:
                print(f"[TestRunner] Test {test.name} passed.")
                self.succeeded_tests.append(test)
                await self.__cache_snapshots(test, worker)
            else:
                print(f"[TestRunner] Test {test.name} failed at step {res.failed_step_index+1}:", res.message)
                self.failed_tests.append(test)
                self.__prune_unrunnable_tests(test)

            self.test_results[test] = res

            self.__worker_done_event.set()
        except Exception as e:
            logging.exception("Unexpected error while running test: ", exc_info=e, stack_info=True)
            raise  # Will cancel the TaskGroup and therefore all tasks

    async def __boot_worker(self, task_group: asyncio.TaskGroup, worker: TestWorker, initial_snapshot: str | None = None):
        print(f"[TestRunner] Booting worker #{worker.wid} with initial_snapshot: {initial_snapshot}")

        await worker.start(initial_snapshot)
        task_group.create_task(worker.on_unexpected_exit(lambda: self.__worker_exit_event.set()))

        print(f"[TestRunner] Worker #{worker.wid} boot complete, setting worker_done_event.")

        self.__worker_done_event.set()

    def __prune_unrunnable_tests(self, failed_test: TestCase):
        self.unrunnable_tests = []

        for t in self.remaining_tests:
            if t.from_ in failed_test.snapshots:
                # If we have an up-to-date snapshot we can still run this test:
                dep_chain = resolve_test_case_dependency_chain(t, self.all_tests)
                if snapshot_cache.snapshot_exists(t.from_, snapshot_cache.checksum(dep_chain)):
                    continue

                print(f"[TestRunner] - Now unrunnable:", t.name, f"(depends on snapshot {t.from_})")
                self.unrunnable_tests.append(t)

                if self.test_status_changed_callback:
                    self.test_status_changed_callback(t, 'unrunnable', None, None)

        for t in self.unrunnable_tests:
            self.remaining_tests.remove(t)

    async def __stop_all_workers(self):
        logging.debug("Shutting down all workers...")
        for worker in self.workers:
            await worker.stop()

    async def __raise_on_worker_exit(self):
        await self.__worker_exit_event.wait()
        raise RuntimeError("Worker exited unexpectedly.")


class TestWorker(QEMUWorker):
    def __init__(self):
        super().__init__()

        self.current_test = None
        self.__is_stopping = False

        self.__screenshot_dir = os.path.join(RUNTIME_TMPDIR, f'worker-{self.wid}-screenshots')  # use a dir not in self.priv_tmpdir so that screenshots survice a self.destroy()

        os.makedirs(self.__screenshot_dir, exist_ok=True)

    async def run_test(self, test: TestCase, status_change_callback: TestStatusChangeCallback | None = None):
        self.current_test = test

        status_change_callback = status_change_callback or (lambda *_: None)  # reduce boilerplate downstream
        results: list[TestStepResult] = []

        logging.debug(f"[Worker {self.wid}] Running test {test.name}")

        status_change_callback(test, 'started', None, None)

        await self.__try_wakeup()

        if test.from_:
            logging.debug(f"[Worker {self.wid}] Loading snapshot {test.from_}")
            await self.load_snapshot(test.from_)
            # status_change_callback(test, 'started', None, None)

        if test.steps:
            with floating_assets(test.assets):
                for i, step in enumerate(test.steps):
                    status_change_callback(test, 'started', None, i)

                    res = await self.__run_step(test, step, i)

                    results.append(res)

                    if not res.success:
                        break

        self.current_test = None
        res = TestResult(step_results=results)
        status_change_callback(test, 'completed', res, None)
        return res

    async def __run_step(self, test: TestCase, step: Step, step_index: int) -> TestStepResult:
        """
        Run a single step, log status updates and create before-and-after screenshots.

        :return: TestStepResult
        """
        before_screenshot = TestScreenshot(
            tag="before",
            path=os.path.join(self.__screenshot_dir, f'{slugify(test.name)}-{step_index:03}-before-{time.time()}.ppm')
        )
        after_screenshot = TestScreenshot(
            tag="after",
            path=os.path.join(self.__screenshot_dir, f'{slugify(test.name)}-{step_index:03}-after-{time.time()}.ppm')
        )
        await self.qmp.screendump(before_screenshot.path)

        logging.info(f"[Worker {self.wid}] Running {step.__class__.__name__}({step})")
        start_time = time.monotonic()

        try:
            await run_action(self, step, test)
            res = TestStepResult(
                success=True,
                duration=time.monotonic() - start_time,
                screenshots=[before_screenshot, after_screenshot],
            )
        except TestException.ActionFailed as e:
            res = TestStepResult(
                success=False,
                duration=time.monotonic() - start_time,
                message=str(e),
                exception=e,
                screenshots=[*e.screenshots, before_screenshot, after_screenshot],
            )

        if res.success:
            logging.debug(f"[Worker {self.wid}] {step.__class__.__name__} succeeded in {res.duration:.3f}s")
        else:
            logging.debug(f"[Worker {self.wid}] {step.__class__.__name__} took {res.duration:.3f}s and"
                          f" failed with {res.message}")

        await self.qmp.screendump(after_screenshot.path)
        return res

    async def __try_wakeup(self):
        try:
            await self.qmp.cmd("system_wakeup")
        except QMPError:
            pass

    @property
    def is_busy(self):
        return (not self.is_ready) or (self.current_test is not None)

    async def start(self, *args, **kwargs):
        await request_asset_server()
        return await super().start(*args, **kwargs)

    async def stop(self):
        self.__is_stopping = True
        try:
            await super().stop()
        finally:
            self.__is_stopping = False

        await unrequest_asset_server()

    async def on_unexpected_exit(self, callback: Callable):
        await self.proc.wait()

        if not self.__is_stopping:
            callback()



class _TestRunnerDone(Exception):
    pass
