from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ShareResType = Literal["dev", "train"]


class ShareBody(BaseModel):
    res_type: ShareResType
    res_id: str = Field(min_length=1)
    target_usernames: list[str] = Field(min_length=1)


class ShareItem(BaseModel):
    res_type: str
    res_id: str
    target_username: str
    shared_by: str
    shared_at: str
