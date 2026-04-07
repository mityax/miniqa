import asyncio
import glob
import hashlib
import json
import os
import shutil

from miniqa.lib.config import CACHE_DIR, CONFIG
from miniqa.lib.test_case.test_case_file import TestCase

SNAPSHOT_CACHE_DIR = os.path.join(CACHE_DIR, 'snapshots')


def snapshot_exists(snapshot_name: str, checksum: str):
    glob_expr = _snapshot_dir(f'*{snapshot_name}*', checksum)
    return len(glob.glob(glob_expr)) > 0

async def add_snapshot(snapshot_names: list[str], checksum: str, disk_dir: str):
    snapshot_cache_dir = _snapshot_dir(snapshot_names, checksum)

    os.makedirs(SNAPSHOT_CACHE_DIR, exist_ok=True)

    # Clear previous snapshots with this name:
    await asyncio.to_thread(_delete_all_snapshots_with_names, snapshot_names)

    # Copy the snapshot over:
    await asyncio.to_thread(shutil.copytree, disk_dir, snapshot_cache_dir)


async def clone_snapshot_to(target_directory: str, snapshot_name: str, checksum: str):
    glob_expr = _snapshot_dir(f'*{snapshot_name}*', checksum)
    cache_dir = glob.glob(glob_expr)[0]
    await asyncio.to_thread(shutil.copytree, cache_dir, target_directory, dirs_exist_ok=True)


def checksum(test_cases: list[TestCase]) -> str | None:
    if not test_cases: return None

    test_cases = sorted(test_cases, key=lambda t: t.name)
    json_str = json.dumps(
        [tc.model_dump() for tc in test_cases],
        sort_keys=True
    )

    # Append the last-modified time of the base image to each checksum to ensure swapping the image
    # results in caches being invalidated:
    json_str += f";{os.path.getmtime(CONFIG.image):.0f}"

    return hashlib.sha256(json_str.encode()).hexdigest()


def _snapshot_dir(snapshot_names: list[str] | str, checksum: str) -> str:
    name = '_'.join(sorted(snapshot_names)) if not isinstance(snapshot_names, str) else snapshot_names
    return os.path.join(SNAPSHOT_CACHE_DIR, f'{name}.{checksum}')


def _delete_all_snapshots_with_names(snapshot_names: list[str]):
    for d in glob.glob(_snapshot_dir(snapshot_names, '*')):
        shutil.rmtree(d)
