from __future__ import annotations

import os
import re
import typing
from dataclasses import dataclass
from typing import Optional, Union, Any, Annotated, Literal, Self, Hashable, TypeVar

import pydantic
import typing_inspection
from pydantic import ConfigDict, Field, BeforeValidator, Discriminator, Tag
from typing_inspection.introspection import inspect_annotation, AnnotationSource

from miniqa.lib.test_case.load_yaml import load_yaml
from miniqa.lib.test_case.model_helpers import NoExtraBaseModel, default_if_none


# === Top‑level model ===


class TestCase(NoExtraBaseModel):
    name: str = Field(exclude=True)
    from_: Optional[str] = Field(default=None, alias="from")
    env: dict[str, Any] | None = None
    defs: dict[str, list[Step]] | None = None
    assets: dict[str, str] = Field(default_factory=dict)
    steps: list[Step] | None = None

    @classmethod
    def from_yaml_file(cls, fn: str) -> 'TestCase':
        with open(fn) as f:
            return cls.from_yaml_text(f.read(), fn)

    @staticmethod
    def from_yaml_text(yaml_text: str, fn: str):
        from miniqa.lib.config import CONFIG  # local import to avoid circular dependency

        # If there are multiple YAML documents in the file, consider only the first - the "---" document
        # separator can be used as a break point in the test:
        data = load_yaml(yaml_text, fn, extra_env=CONFIG.env, allow_env_from_key='env', allow_extra_docs=True)
        data["name"] = os.path.splitext(os.path.basename(fn))[0]

        return TestCase(**data)

    @property
    def snapshots(self):
        """All snapshots created/updated by this [TestCase]"""
        return set(
            step.snapshot
            for step in self.steps
            if isinstance(step, SnapshotStep)
        )

    def __hash__(self) -> int:
        return hash(self.name)

    class Config:
        @staticmethod
        def json_schema_extra(schema: dict[str, Any], model: 'Self') -> None:
            # This translates each steps choice into a `oneOf` instead of an `anyOf`, which pydantic
            # generates. This is to ensure the schema correctly asserts that properties of different
            # step types must not be mixed in each step object (i.e. each step can only be of
            # exactly one type, and only have the corresponding properties):
            for schema_option in schema["properties"]["steps"]["anyOf"]:
                if "items" in schema_option:  # unwrap array
                    schema_option = schema_option["items"]
                    if "anyOf" in schema_option:
                        schema_option["oneOf"] = schema_option["anyOf"]
                        del schema_option["anyOf"]



# === Step test_case ===
class _BaseStep(pydantic.BaseModel):
    pass

# Single‑literal actions (value is passed directly as `args`)

class SleepStep(_BaseStep, NoExtraBaseModel):
    sleep: str | float | int


class KeyPressStep(_BaseStep, NoExtraBaseModel):
    key_press: str


class KeyReleaseStep(_BaseStep, NoExtraBaseModel):
    key_release: str


class InvokeKeyStep(_BaseStep, NoExtraBaseModel):
    invoke_key: str


class InvokeKeysStep(_BaseStep, NoExtraBaseModel):
    invoke_keys: list[str]
    sequential: bool = True
    speed: Speed = 1.0


class TypeTextStep(_BaseStep, NoExtraBaseModel):
    type_text: str
    speed: Speed = 1.0


class SnapshotStep(_BaseStep, NoExtraBaseModel):
    snapshot: str


# Object‑argument actions

class MouseMoveStep(_BaseStep, NoExtraBaseModel):
    mouse_move: AnyPosition


class MousePressStep(_BaseStep, NoExtraBaseModel):
    mouse_press: MouseButtonArgs | AnyPosition


class MouseReleaseStep(_BaseStep, NoExtraBaseModel):
    mouse_release: MouseButtonArgs | AnyPosition


class ClickStep(_BaseStep, NoExtraBaseModel):
    click: Annotated[MouseButtonArgs | AnyPosition, BeforeValidator(default_if_none)] = pydantic.Field(default_factory=lambda: MouseButtonArgs())


class TouchPressStep(_BaseStep, NoExtraBaseModel):
    touch_press: TouchArgs | AnyPosition


class TouchMoveStep(_BaseStep, NoExtraBaseModel):
    touch_move: TouchArgs | AnyPosition


class TouchReleaseStep(_BaseStep, NoExtraBaseModel):
    touch_release: TouchArgs | AnyPosition


class TouchStep(_BaseStep, NoExtraBaseModel):
    touch: list[TouchArgs | AnyPosition] | TouchArgs | AnyPosition
    speed: Speed = 1.0


class ScreenshotStep(_BaseStep, NoExtraBaseModel):
    screenshot: ScreenshotArgs


class WaitStep(_BaseStep, NoExtraBaseModel):
    wait: Annotated[WaitArgs, BeforeValidator(default_if_none)] = pydantic.Field(default_factory=lambda: WaitArgs())


class AssertStep(_BaseStep, NoExtraBaseModel):
    assert_: FindElement = pydantic.Field(alias="assert")


class CustomStep(_BaseStep):
    """
    A fallback step that can be anything; allows calling a custom step defined in `defs`, e.g.:

    ```yaml
    defs:
        wait_then_touch_center:
            - wait:
            - touch: center

    steps:
        - wait_then_touch_center:
    ```
    """
    model_config = pydantic.ConfigDict(extra="allow")


# === Step union ===

# Real implementation below, this just serves as forward ref
def _sd(value: dict | Step) -> Hashable: return _step_discriminator(value)

Step = Annotated[
    Union[
        # Single‑literal value:
        Annotated[SleepStep, Tag('sleep')],
        Annotated[KeyPressStep, Tag('key_press')],
        Annotated[KeyReleaseStep, Tag('key_release')],
        Annotated[InvokeKeyStep, Tag('invoke_key')],
        Annotated[InvokeKeysStep, Tag('invoke_keys')],
        Annotated[TypeTextStep, Tag('type_text')],
        Annotated[SnapshotStep, Tag('snapshot')],

        # Object value:
        Annotated[MouseMoveStep, Tag('mouse_move')],
        Annotated[MousePressStep, Tag('mouse_press')],
        Annotated[MouseReleaseStep, Tag('mouse_release')],
        Annotated[ClickStep, Tag('click')],
        Annotated[TouchPressStep, Tag('touch_press')],
        Annotated[TouchMoveStep, Tag('touch_move')],
        Annotated[TouchReleaseStep, Tag('touch_release')],
        Annotated[TouchStep, Tag('touch')],
        Annotated[ScreenshotStep, Tag('screenshot')],
        Annotated[AssertStep, Tag('assert')],

        # Optional object value:
        Annotated[WaitStep, Tag('wait')],
        Annotated[CustomStep, Tag('<custom_step>')],
    ],
    Discriminator(_sd)
]

_step_to_tag = {s.__origin__: s.__metadata__[0].tag for s in typing.get_args(Step.__origin__)}
_tag_to_step = {v: k for k, v in _step_to_tag.items()}

def _step_discriminator(value: dict | Step) -> Hashable:
    if isinstance(value, dict):
        for k in value.keys():
            if k in _tag_to_step:
                return k
        return "<custom_step>"
    elif isinstance(value, _BaseStep):
        return _step_to_tag[value.__class__]  # if this fails, a Step is missing in the `Steps` Union above

    raise ValueError(f"Invalid step type: {type(value)}: {value!r}")


# === Argument test_case ===

class MouseButtonArgs(NoExtraBaseModel):
    button: Literal['left', 'middle', 'right'] = 'left'
    position: AnyPosition | None = None

    @staticmethod
    def create_from(value: 'MouseButtonArgs | AnyPosition | None') -> 'MouseButtonArgs':
        if isinstance(value, MouseButtonArgs):
            return value
        return MouseButtonArgs(position=value)


class TouchArgs(NoExtraBaseModel):
    position: AnyPosition
    slot: int = 0

    @staticmethod
    def create_from(value: 'TouchArgs | AnyPosition | None') -> 'TouchArgs':
        if isinstance(value, TouchArgs):
            return value
        return TouchArgs(position=value)


class ScreenshotArgs(NoExtraBaseModel):
    name: str
    regions: RegionOrRegions | None = None
    max_diff: str | float | int = 0.01


class WaitArgs(NoExtraBaseModel):
    for_: str | WaitForArgs | FindElement | None = Field(default=None, alias="for")
    regions: RegionOrRegions | None = None
    diff: str | float | int = 0.01
    check_interval: str | float | int | None = None
    timeout: str | float | int = 30

    model_config = ConfigDict(populate_by_name=True)

class WaitForArgs(NoExtraBaseModel):
    dominant_color: str


# Reusable types/value types:

class RegionDict(NoExtraBaseModel):
    x: int | str
    y: int | str
    width: int | str
    height: int | str

Region = tuple[int, int, int, int] | str | RegionDict

RegionOrRegions = Region | list[Region]


class FindElement(NoExtraBaseModel):
    find: FindElementArgs

class FindElementArgs(NoExtraBaseModel):
    text: str
    background_color: str | None = None
    location_hint: CoordinatePosition | None = None


class CoordinatesDict(NoExtraBaseModel):
    x: int | str
    y: int | str

CoordinatePosition =tuple[int, int] | str | CoordinatesDict | \
                    Literal['right', 'left', 'top', 'bottom', 'center',
                           'top-left', 'top-right', 'bottom-left', 'bottom-right',
                           'top-center', 'right-center', 'bottom-center', 'left-center']
AnyPosition = CoordinatePosition | FindElement

Speed = float | int | Literal['slow', 'slower', 'normal', 'faster', 'fast'] | str


# === Value converters ===

def to_seconds(value: str | float | int) -> float:
    if isinstance(value, str):
        if m := re.match(r"(\d+(\.\d+)?)(s|ms)$", value.strip()):
            return float(m.group(1)) * (1 if m.group(3) == 's' else 0.001)
        else:
            raise ValueError(f"Invalid time value: '{value}'")

    return value

def to_ratio(value: str | int | float) -> float:
    if isinstance(value, str):
        if m := re.match(r"(\d+(\.\d+)?)%$", value):
            value = float(m.group(1)) / 100
        else:
            raise ValueError(f"Invalid ratio value: '{value}'")
    return value

def to_speed_factor(value: Speed) -> float:
    value = {
        'slow': 0.5,
        'slower': 0.75,
        'normal': 1.0,
        'faster': 1.25,
        'fast': 1.5,
    }.get(value, value)

    if isinstance(value, str):
        try:
            value = to_ratio(value)
        except ValueError:
            raise ValueError(f"Invalid speed value: '{value}'")

    if value <= 0:
        raise ValueError(f"Speed must be greater than 0, but got: {value}")

    return value



ParsedRegion = tuple['ParsedCoordinate', 'ParsedCoordinate', 'ParsedCoordinate', 'ParsedCoordinate']

def to_parsed_region(value: Region) -> ParsedRegion:
    match value:
        case list() | tuple() if len(value) == 4:
            coords = value
        case str() if re.match(r"(-?(\d+(\.\d+)?%|\d+px)(\s+|$)){4}$", value.strip()):
            coords = list(re.split(r"\s+", value))
        case RegionDict(x=x, y=y, width=width, height=height):
            coords = (x, y, width, height)
        case list() | tuple():
            raise ValueError(f"Region must have exactly 4 integer or string elements: x, y, width and height, "
                             f"but got: {value}")
        case str():
            raise ValueError(f"Region strings must follow this format: \"<float-x>% <float-y>% <float-width>%"
                             f" <float-height>%\" or \"<int-x>px <int-y>px <int-width>px <int-height>px\", but"
                             f" got: \"{value.strip()}\"")

    return tuple(parse_coordinate(c) for c in coords)


def to_parsed_regions(value: RegionOrRegions | None) -> list[ParsedRegion]:
    if value is None:
        return []

    try:
        return [to_parsed_region(value)]
    except ValueError:
        return [to_parsed_region(r) for r in value]


ParsedPosition = tuple['ParsedCoordinate', 'ParsedCoordinate']

_LOCATION_ALIASES: dict[str, tuple[float, float]] = {
    # cardinal
    "left": (0.0, 0.5),
    "right": (1.0, 0.5),
    "top": (0.5, 0.0),
    "bottom": (0.5, 1.0),
    "center": (0.5, 0.5),
    # diagonals
    "top-left": (0.0, 0.0),
    "top-right": (1.0, 0.0),
    "bottom-left": (0.0, 1.0),
    "bottom-right": (1.0, 1.0),
    # edges
    "top-center": (0.5, 0.0),
    "right-center": (1.0, 0.5),
    "bottom-center": (0.5, 1.0),
    "left-center": (0.0, 0.5),
}


def to_parsed_position(value: tuple[int, int] | str | CoordinatesDict) -> ParsedPosition:
    match value:
        case tuple() | list() if len(value) == 2:
            coords = value
        case str() if value in _LOCATION_ALIASES:
            coords = [ParsedCoordinate.rel(v) for v in _LOCATION_ALIASES[value]]
        case str() if re.match(r"((-?\d+(\.\d+)?%|-?\d+px)(\s+|$)){2}$", value.strip()):
            coords = list(re.split(r"\s+", value))
        case str():
            raise ValueError(f"Position strings must follow this format: \"<float-x>% <float-y>%\" or \"<int-x>px "
                             f"<int-y>px\", or a known location alias such as \"top-right\", but got: "
                             f"\"{value.strip()}\"")
        case tuple() | list():
            raise ValueError("Position tuples must have exactly 2 integer or string elements: x and y")
        case _:
            raise ValueError(f"Invalid position value: {value}")

    return tuple(parse_coordinate(c) for c in coords)

def parse_coordinate(c: str | int | ParsedCoordinate) -> ParsedCoordinate:
    match c:
        case str() if c.endswith("%"):
            return ParsedCoordinate(value=float(c[:-1]) / 100, is_relative=True)
        case str() if c.endswith("px"):
            return ParsedCoordinate(value=int(c[:-2]), is_relative=False)
        case int():
            return ParsedCoordinate(value=c, is_relative=False)
        case ParsedCoordinate():
            return c

    raise ValueError(f"Invalid coordinate value: {c}")

# === Utilities ===

@dataclass
class ParsedCoordinate:
    value: float
    is_relative: bool

    def to_abs(self, max_extend: int, normalize_negative: bool = True) -> int:
        if not self.is_relative:
            res = round(self.value)
        else:
            res = round(self.value * max_extend)

        if normalize_negative and res < 0:
            res = max_extend + res

        return res

    def to_rel(self, max_extend: int, normalize_negative: bool = True) -> float:
        if self.is_relative:
            res = self.value
        else:
            res = self.value / max_extend

        if normalize_negative and res < 0:
            res = 1 + res

        return res


    @classmethod
    def abs(cls, value: int) -> 'Self':
        return cls(value=value, is_relative=False)

    @classmethod
    def rel(cls, value: float) -> 'Self':
        return cls(value=value, is_relative=True)
