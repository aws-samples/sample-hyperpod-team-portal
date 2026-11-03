"""通用 Secret schemas (B2 每人一把)。

用户只管 key-value; secret 名平台自动派生 <owner>-secrets (用户无感)。
value 只进 k8s Secret, 不落 DDB, 建后不回显; 只回 key 名不含 value。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SecretKeyPut(BaseModel):
    """加/改一个凭证 (key-value)。同 key 覆盖 = 更新。"""

    key: str = Field(min_length=1, max_length=253)
    value: str = Field(min_length=1, max_length=8192)


class SecretView(BaseModel):
    """本人 Secret 视图 (只含 key 名, 不含 value)。"""

    keys: list[str]
