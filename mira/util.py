"""通用小工具：ID 生成、UTC 时间戳。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone


def new_id(prefix: str) -> str:
    """生成带前缀的短 ID，如 ``sess_a1b2c3d4e5f6``。"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def short_hash(text: str, length: int = 7) -> str:
    """对文本取短哈希（base36 小写字母数字），用于目录 / ID 命名，如 ``123hxs1``。"""
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    n = int(digest, 16)
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n and len(out) < length:
        n, rem = divmod(n, 36)
        out = chars[rem] + out
    return out.rjust(length, "0")


def new_session_id() -> str:
    """生成 session id：短哈希（hashcode）。"""
    return short_hash(uuid.uuid4().hex, length=10)


def count_tokens(text: str) -> int:
    """按字符粗估 token 数（4 字符 ≈ 1 token）。"""
    return max(1, len(text) // 4)


def utcnow_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串（毫秒精度，Z 后缀），如 2026-08-11T10:00:00.123Z。"""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def split_spec(spec: str | None) -> tuple[str, str]:
    """模型串 {provider}/{model} → (provider, model)。

    模型始终以 {provider}/{model} 携带 provider（决策 #26）：provider 与模型绑定，
    任何时刻都可由模型长名反推；无 '/'（缺 provider）抛 ValueError，
    不设默认 provider。
    """
    if spec and "/" in spec:
        provider, _, model = spec.partition("/")
        provider = provider.strip()
        if not provider:
            raise ValueError(f"模型必须以 {{provider}}/{{model}} 形式指定（缺 provider: {spec!r}）")
        return provider, model.strip()
    raise ValueError(f"模型必须以 {{provider}}/{{model}} 形式指定（缺 provider: {spec!r}）")
