"""Tokenizers producing app.schemas.tokenization.TokenizationResult.

Real token IDs only come from a real tokenizer. Without one the result is a clearly
labelled approximation with no IDs.
"""

from __future__ import annotations

import re
from typing import Protocol

from app.schemas.tokenization import DISCLAIMER, TokenizationResult, TokenUnit

# Words, numbers, single punctuation marks: a rough stand-in for subword tokens.
_APPROX_RE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")


class Tokenizer(Protocol):
    name: str

    def tokenize(self, text: str) -> TokenizationResult: ...


class ApproximateTokenizer:
    name = "regex_word_level"

    def tokenize(self, text: str) -> TokenizationResult:
        tokens = [
            TokenUnit(index=i, text=m.group(0), start=m.start(), end=m.end(), is_approximate=True)
            for i, m in enumerate(_APPROX_RE.finditer(text))
        ]
        return TokenizationResult(
            raw_text=text, tokens=tokens, tokenizer_name=self.name, is_live_model_tokenization=False,
            note="Approximation: words and punctuation split by a regex, not the model's real tokens; "
                 "no token IDs. " + DISCLAIMER,
        )


class TiktokenTokenizer:
    """Real BPE tokenizer. Exact for its encoding, which may differ from the active model's."""

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        import tiktoken  # optional dependency

        self._encoding = tiktoken.get_encoding(encoding_name)
        self.name = encoding_name

    def tokenize(self, text: str) -> TokenizationResult:
        ids = self._encoding.encode(text)
        _, starts = self._encoding.decode_with_offsets(ids)
        ends = [*starts[1:], len(text)]
        tokens = [
            TokenUnit(index=i, text=text[s:e], start=s, end=e, token_id=tid)
            for i, (tid, s, e) in enumerate(zip(ids, starts, ends))
        ]
        return TokenizationResult(
            raw_text=text, tokens=tokens, tokenizer_name=self.name, is_live_model_tokenization=True,
            note=f"Real token IDs from {self.name}; the selected model may use a different tokenizer. "
                 + DISCLAIMER,
        )


def get_tokenizer(prefer_real: bool = True) -> Tokenizer:
    if prefer_real:
        try:
            return TiktokenTokenizer()
        except Exception:  # not installed, or encoding files unavailable offline: use the labelled approximation
            pass
    return ApproximateTokenizer()
