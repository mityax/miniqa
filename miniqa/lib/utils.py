import asyncio
import contextlib
import os
import re
import sys
import time

from tqdm.contrib import DummyTqdmFile

from miniqa.lib.config import CONFIG
from miniqa.lib.test_case.test_case_file import TestCase


def list_tests(pth: str | None = None):
    return sorted([
        os.path.join(pth or CONFIG.tests_directory, f)
        for f in os.listdir(pth or CONFIG.tests_directory)
        if f.endswith(".yaml") or f.endswith(".yml")
    ])

def load_tests() -> list[TestCase]:
    return [TestCase.from_yaml_file(fn) for fn in list_tests()]


def slugify(value: str) -> str:
    return re.sub(r'\W', "_", value.lower())


def format_color(color: tuple[int, int, int]) -> str:
    return f"#{''.join('{:02X}'.format(a) for a in color)}"


class timed_cached_property:
    """
    A property decorator that caches its value for a specified TTL (seconds)
    of monotonic time. Works for both regular and async methods.
    """

    def __init__(self, ttl: float):
        self.ttl = ttl
        self._cache: dict[int, tuple] = {}  # id(instance) -> (value, expiry)
        self.func = None
        self.attrname = None

    def __call__(self, func):
        self.func = func
        self.attrname = func.__name__
        return self

    def __set_name__(self, owner, name):
        self.attrname = name

    def _get_cached(self, instance):
        entry = self._cache.get(id(instance))
        if entry is not None:
            value, expiry = entry
            if time.monotonic() < expiry:
                return value, True
        return None, False

    def _set_cached(self, instance, value):
        self._cache[id(instance)] = (value, time.monotonic() + self.ttl)
        return value

    def __get__(self, instance, owner):
        if instance is None:
            return self

        if asyncio.iscoroutinefunction(self.func):
            # Always return a coroutine so the caller can always `await` it,
            # regardless of whether the value comes from cache or a fresh call.
            return self._async_get(instance)

        # Sync path
        value, valid = self._get_cached(instance)
        if valid:
            return value
        return self._set_cached(instance, self.func(instance))

    async def _async_get(self, instance):
        value, valid = self._get_cached(instance)
        if valid:
            return value
        return self._set_cached(instance, await self.func(instance))


@contextlib.contextmanager
def std_out_err_redirect_tqdm():
    orig_out_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = map(DummyTqdmFile, orig_out_err)
        yield orig_out_err[0]
    # Relay exceptions
    except Exception as exc:
        raise exc
    # Always restore sys.stdout/err if necessary
    finally:
        sys.stdout, sys.stderr = orig_out_err


# === Output helpers ===

class ANSIColor:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'  # The reset code

def print_markup(*text: str):
    """
    This helper automatically strips out ANSI color codes if they're unlikely to be supported.

    Use as:

    ```
    print_markup(f"This is a {ANSIColor.BOLD}bold{ANSIColor.END} word")
    ```

    or

    ```
    print_markup("This is a", ANSIColor.BOLD, "bold", ANSIColor.END, " word")
    ```
    """
    text = "".join(text)
    if not supports_color():
        text = re.sub(r"\033\[\d+m", "", text)
    print(text)

def in_ci():
    return bool(os.environ.get("CI"))

def supports_color(stream=None):
    stream = stream or sys.stdout

    # Explicit user preferences first
    if os.environ.get("NO_COLOR", "false") in ("1", "true", "yes"):
        return False
    if (os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE", "false")).lower() in ("1", "true", "yes"):
        return True

    # Known CI systems where ANSI usually works:
    if any(os.environ.get(var) for var in {"GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "TRAVIS", "BUILDKITE",
                                           "TF_BUILD", "BITBUCKET_BUILD_NUMBER"}):
        return True

    if not stream.isatty() or os.environ.get("TERM") == "dumb":
        return False

    return True

def supports_tqdm():
    return not in_ci() and sys.stdout.isatty()
