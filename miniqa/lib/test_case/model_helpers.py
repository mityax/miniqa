from typing import Any

import pydantic
from pydantic_core import PydanticUseDefault


# === Base model config ===
class NoExtraBaseModel(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='forbid')


def default_if_none(value: Any) -> Any:
    if value is None:
        raise PydanticUseDefault()
    return value

