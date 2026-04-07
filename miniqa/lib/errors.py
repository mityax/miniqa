from abc import ABC

from miniqa.lib.runner.test_models import TestScreenshot
from miniqa.lib.test_case import test_case_file as f


class TestException:
    class ActionFailed(Exception, ABC):
        @property
        def screenshots(self) -> list[TestScreenshot]:
            return []

    class WaitTimedOut(ActionFailed):
        def __init__(self, message: str, reference_image: str | None = None, reference_name: str | None = None,
                     regions: list[f.ParsedRegion] | None = None, ignore_regions: list[f.ParsedRegion] | None = None):
            super().__init__(message)
            self.reference_image = reference_image
            self.reference_name = reference_name
            self.regions = regions
            self.ignore_regions = ignore_regions

        @property
        def screenshots(self) -> list[TestScreenshot]:
            if self.reference_image:
                return [
                    TestScreenshot(tag='reference', path=self.reference_image, name=self.reference_name),
                ]
            return []


    class ImageMismatch(ActionFailed):
        def __init__(self, message: str, reference_name: str, reference_image: str, actual_image: str,
                     regions: list[f.ParsedRegion] | None = None, ignore_regions: list[f.ParsedRegion] | None = None):
            super().__init__(message)
            self.reference_name = reference_name
            self.reference_image = reference_image
            self.actual_image = actual_image
            self.regions = regions
            self.ignore_regions = ignore_regions

        @property
        def screenshots(self) -> list[TestScreenshot]:
            return [
                TestScreenshot(tag="reference", path=self.reference_image, name=self.reference_name),
                TestScreenshot(tag="actual", path=self.actual_image),
            ]

    class PositionNotFound(ActionFailed):
        pass
