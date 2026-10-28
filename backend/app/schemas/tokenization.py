"""Tokenization display schema (INTERFACE_CONTRACTS.md section 4).

Token IDs appear only when a real tokenizer produced them. An approximation carries
no IDs at all, so the UI can never show invented numbers.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

DISCLAIMER = "Tokenization is shown for inspection only; it does not decide any physical action."


class TokenUnit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    text: str
    start: int = Field(ge=0, description="Character offset into raw_text (inclusive).")
    end: int = Field(ge=0, description="Character offset into raw_text (exclusive).")
    token_id: Optional[int] = None
    is_approximate: bool = False
    role: Optional[str] = None

    @model_validator(mode="after")
    def _honest(self) -> "TokenUnit":
        if self.is_approximate and self.token_id is not None:
            raise ValueError("an approximate token must not carry a token ID")
        if not self.is_approximate and self.token_id is None:
            raise ValueError("a real token needs its token ID")
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class TokenizationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_text: str
    tokens: list[TokenUnit]
    tokenizer_name: str = Field(min_length=1)
    is_live_model_tokenization: bool
    note: str = DISCLAIMER

    @property
    def is_approximate(self) -> bool:
        return not self.is_live_model_tokenization

    @property
    def count(self) -> int:
        return len(self.tokens)

    @model_validator(mode="after")
    def _consistent(self) -> "TokenizationResult":
        for i, tok in enumerate(self.tokens):
            if tok.index != i:
                raise ValueError("token indexes must be 0..n-1 in order")
            if tok.is_approximate == self.is_live_model_tokenization:
                raise ValueError("every token's is_approximate must match the result")
            if self.raw_text[tok.start : tok.end] != tok.text:
                raise ValueError(f"token {i} offsets do not reslice raw_text")
        return self
