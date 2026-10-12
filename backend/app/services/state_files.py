"""Controlled, process-safe filesystem boundary for conversation and memory state."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.state_home import checked_path
from app.core.storage_layout import state_root


class MemoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal[1] = 1
    context_window_tokens: int = Field(default=32000, ge=1024, le=2000000)
    auto_compact_token_limit: int = Field(default=24000, ge=256)
    response_reserve_tokens: int = Field(default=4096, ge=128)
    summary_max_tokens: int = Field(default=2000, ge=64)
    recent_turns: int = Field(default=10, ge=10, le=10)
    long_term_memory_enabled: bool = True
    memory_min_idle_hours: float = Field(default=6, ge=0, le=720)
    memory_max_age_days: int = Field(default=30, ge=1, le=365)
    memory_batch_size: int = Field(default=16, ge=1, le=128)
    memory_poll_seconds: int = Field(default=60, ge=1, le=3600)
    memory_context_tokens: int = Field(default=2000, ge=64)

    @model_validator(mode="after")
    def budget(self):
        if self.auto_compact_token_limit > self.context_window_tokens - self.response_reserve_tokens:
            raise ValueError("压缩阈值必须为回复预留上下文空间")
        if self.summary_max_tokens >= self.auto_compact_token_limit:
            raise ValueError("摘要预算必须小于压缩阈值")
        return self


def safe_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(value)):
        raise ValueError("无效的状态标识")
    return str(value)


class StateFiles:
    def __init__(self, settings):
        self.root = state_root(settings)
        self._lock = RLock()
        self._locks = {}

    def path(self, *parts):
        target = self.root.joinpath(*parts)
        for candidate in (target, *target.parents):
            if not candidate.is_relative_to(self.root):
                break
            if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
                raise RuntimeError("状态路径不能包含符号链接")
        if not target.resolve().is_relative_to(self.root):
            raise ValueError("状态路径越界")
        return target

    @contextmanager
    def lock(self, key):
        """One byte OS lock, shared by all workers on Windows and POSIX."""
        with self._lock:
            local_lock = self._locks.setdefault(key, RLock())
        with local_lock:
            path = self.path("thread-writer-locks", sha256(key.encode()).hexdigest() + ".lock")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a+b") as handle:
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def atomic_write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return
        fd, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def policy_toml(policy):
        values = policy.model_dump()
        version = values.pop("format_version")
        return f"format_version = {version}\n\n[memory]\n" + "".join(
            f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in values.items())

    def policy(self):
        path = self.path("config.toml")
        if not path.exists():
            with self.lock("policy"):
                if not path.exists():
                    legacy = self.path("config.json")
                    try:
                        if legacy.exists() and legacy.stat().st_size > 65536:
                            raise ValueError()
                        policy = MemoryPolicy.model_validate_json(legacy.read_text(encoding="utf-8")) if legacy.exists() else MemoryPolicy()
                    except (ValueError, OSError):
                        raise RuntimeError("旧记忆配置无效，转换已停止") from None
                    self.atomic_write(path, self.policy_toml(policy))
                    if legacy.exists():
                        backup = self.path("backups", "legacy-config.json")
                        self.atomic_write(backup, legacy.read_text(encoding="utf-8"))
                        legacy.unlink()
        try:
            if path.stat().st_size > 65536:
                raise ValueError()
            document = tomllib.loads(path.read_text(encoding="utf-8"))
            if set(document) - {"format_version", "memory"}:
                raise ValueError()
            if "format_version" in document["memory"]:
                raise ValueError()
            return MemoryPolicy.model_validate({"format_version": document["format_version"], **document["memory"]})
        except (ValueError, OSError, KeyError, TypeError):
            raise RuntimeError(".mindpoilt/config.toml 无效，请检查记忆参数和 token 预算") from None
