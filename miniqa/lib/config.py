from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import time
from typing import Any

import pydantic
from pydantic import model_validator

from .test_case.load_yaml import load_yaml
from .test_case.model_helpers import NoExtraBaseModel
from .test_case.test_case_file import RegionOrRegions


class ConfigFile(NoExtraBaseModel):
    image: str
    initial_snapshot: str | None = None
    tests_directory: str = './tests'
    out_directory: str = './out'
    refs_directory: str = './refs'
    cache_directory: str | None = None
    qemu_args: list[str] = pydantic.Field(default_factory=lambda: [])
    headless: bool = True
    serve_assets: list[str] = pydantic.Field(default_factory=lambda: [])
    use_ovmf: bool | OVMFConfig = False
    ignore_regions: RegionOrRegions | None = None
    env: dict[str, Any] = pydantic.Field(default_factory=lambda: {})
    defs: Any | None = None

    @model_validator(mode="before")
    @classmethod
    def split_image_tag(cls, data):
        if isinstance(data, dict):
            image = data.get("image")
            snapshot = data.get("initial_snapshot")

            if image and ":" in image and snapshot is None:
                img, tag = image.rsplit(":", 1)
                data["image"] = img
                data["initial_snapshot"] = tag

            if data.get('use_ovmf') == True:
                data["use_ovmf"] = OVMFConfig()

        return data

class OVMFConfig(NoExtraBaseModel):
    code_path: str | list[str] | None = ['/usr/share/OVMF/OVMF_CODE_4M.fd', '/usr/share/OVMF/OVMF_CODE.fd']
    vars_path: str | list[str] | None = ['/usr/share/OVMF/OVMF_VARS_4M.fd', '/usr/share/OVMF/OVMF_VARS.fd']


if os.path.isfile('./miniqa.yml'):
    with open('./miniqa.yml') as f:
        data = load_yaml(f.read(), './miniqa.yml', allow_env_from_key='env')
    CONFIG = ConfigFile(**(data or {}))
else:
    raise RuntimeError("No miniqa.yml found.")


CACHE_DIR = os.path.join(CONFIG.cache_directory, 'cache') if CONFIG.cache_directory else "./miniqa-cache/cache"
"""A possibly temporary directory to use for caching, across multiple runs."""

RUNTIME_TMPDIR = os.path.join(CONFIG.cache_directory, f'miniqa-run-{os.getpid()}-{time.time()}') if CONFIG.cache_directory else tempfile.mkdtemp('miniqa-runtime')
"""A runtime-specific temporary directory, deleted upon exit."""

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(RUNTIME_TMPDIR, exist_ok=True)

atexit.register(lambda: shutil.rmtree(RUNTIME_TMPDIR))

