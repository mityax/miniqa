import asyncio
import logging
import sys
from pathlib import Path

import websockify  # noqa: Ensure at startup we can call the subprocess later

from miniqa.lib.config import CONFIG
from miniqa.lib.test_case.test_case_file import TestCase


def list_tests() -> list[dict]:
    """Scan the tests directory and return a list of {stem, filename, yaml} dicts."""

    tests = []

    if not Path(CONFIG.tests_directory).exists():
        return tests

    for f in sorted(Path(CONFIG.tests_directory).glob("*.yml")) + sorted(Path(CONFIG.tests_directory).glob("*.yaml")):
        try:
            text = f.read_text()
            tests.append({"stem": f.stem, "filename": f.name, "yaml": text})
        except OSError:
            pass

    return tests


def _validate_pipeline(tests: list[TestCase]) -> list[dict]:
    """Return a list of validation error objects for the pipeline view."""

    errors: list[dict] = []

    if not tests:
        return errors

    all_snapshots: dict[str, list[str]] = {}  # snapshot -> [providers]
    for t in tests:
        for s in (t.snapshots or set()):
            all_snapshots.setdefault(s, []).append(t.name or "?")

    # 1. Ensure at least one root (no "from" field):
    if all(t.from_ for t in tests):
        errors.append({
            "scope": "global",
            "message": "There is no test without a 'from' field – the pipeline has no starting point.",
        })

    # 2. Check for duplicate snapshot providers:
    for snapshot, providers in all_snapshots.items():
        if len(providers) > 1:
            for t in tests:
                if snapshot in (t.snapshots or set()):
                    errors.append({
                        "scope": "test",
                        "test_name": t.name,
                        "message": f"Snapshot '{snapshot}' is also provided by: "
                                        + ", ".join(p for p in providers if p != t.name),
                    })

    # 3. Check for missing snapshots depended upon:
    for t in tests:
        if t.from_ and t.from_ not in all_snapshots:
            errors.append({
                "scope": "test",
                "test_name": t.name,
                "message": f"Required snapshot '{t.from_}' is not created by any test.",
            })

    # 4. Check for circular dependencies:
    for t in tests:
        visited: list[str] = []
        current_test: TestCase | None = t

        while current_test and current_test.from_:
            current_test = next((t for t in tests if current_test.from_ in t.snapshots), None)

            if current_test.name in visited:
                errors.append({
                    "scope": "test",
                    "test_name": t.name,
                    "message": "Circular snapshot dependency detected: " + " → ".join(visited),
                })
                break

            visited.append(current_test.name)

    return errors


def try_parse_testcase(yaml_text: str, fn_or_stem: str) -> TestCase | None:
    try:
        return TestCase.from_yaml_text(yaml_text, fn_or_stem)
    except Exception as e:
        logging.debug(f"YAML parsing failed for '{fn_or_stem}'", exc_info=e, stack_info=True)
        return None


class WebsockifyManager:
    def __init__(self):
        self.proc: asyncio.subprocess.Process | None = None

    async def start(self, host: str, listen_port: int, target_port: int) -> asyncio.subprocess.Process | None:
        """
        Start a novnc server so the frontend can show the VM screen.
        """

        await self.stop()


        print("[webui] Starting NoVNC server...")

        try:
            self.proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "websockify",
                f"{host}:{listen_port}",
                f"{host}:{target_port}",
                #stdout=asyncio.subprocess.DEVNULL,
                #stderr=asyncio.subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[webui] novnc launch failed: {e}", file=sys.stderr)


    async def stop(self):

        if self.proc:
            print("[webui] Stopping websockify proxy...")

            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except:
                pass
            self.proc = None

    def is_running(self) -> bool:
        return self.proc and self.proc.returncode is None

