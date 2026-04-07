from typing import Literal, Callable

import pydantic

from miniqa.lib.test_case.test_case_file import TestCase


class TestResult(pydantic.BaseModel):
    step_results: list[TestStepResult] = pydantic.Field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(s.success for s in self.step_results)

    @property
    def failed_step(self) -> TestStepResult | None:
        return self.step_results[self.failed_step_index] if self.failed_step_index is not None else None

    @property
    def message(self) -> str | None:
        return self.step_results[self.failed_step_index].message if self.failed_step_index is not None else None

    @property
    def exception(self) -> Exception | None:
        return self.step_results[self.failed_step_index].exception if self.failed_step_index is not None else None

    @property
    def failed_step_index(self) -> int | None:
        if failed_idx := [i for i, s in enumerate(self.step_results) if not s.success]:
            return failed_idx[0]
        return None

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.step_results)


class TestStepResult(pydantic.BaseModel):
    success: bool
    duration: float
    message: str | None = None
    exception: Exception | None = None
    screenshots: list[TestScreenshot] = pydantic.Field(default_factory=list)

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)


class TestScreenshot(pydantic.BaseModel):
    tag: Literal['before', 'after'] | str
    path: str
    name: str | None = None


TestStatus = Literal['queued', 'started', 'completed', 'unrunnable']
TestStatusChangeCallback = Callable[[TestCase, TestStatus, TestResult | None, int | None], None]


