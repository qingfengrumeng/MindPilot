"""Upgrade the local state home without overwriting an existing installation."""
from contextlib import contextmanager
import os
from pathlib import Path
from threading import RLock


_migration_lock = RLock()


def checked_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise RuntimeError("状态迁移路径不能包含符号链接")
    return path


@contextmanager
def migration_lock(root):
    with _migration_lock:
        with (root / ".sqlite-maintenance.lock").open("a+b") as handle:
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


def prepare_state_home(project_root, data_dir):
    """Prepare Agent directories only; database separation has its own migration."""
    project_root = checked_path(project_root)
    root = checked_path(project_root / ".mindpoilt")
    legacy = checked_path(project_root / "mindpoilt")
    with _migration_lock:
        if legacy.exists():
            if root.exists():
                raise RuntimeError("新旧状态目录同时存在，请先合并数据，避免覆盖会话")
            try:
                legacy.rename(root)
            except FileNotFoundError:
                if not root.is_dir():
                    raise
        root.mkdir(parents=True, exist_ok=True)
    database = checked_path(root / "state_1.sqlite")
    with migration_lock(root):
        old_locks = checked_path(root / "locks")
        locks = checked_path(root / "thread-writer-locks")
        if old_locks.exists() and not locks.exists():
            old_locks.rename(locks)
        for name in ("sessions", "archived_sessions", "memories", "thread-writer-locks", "tmp", "backups"):
            checked_path(root / name).mkdir(exist_ok=True)
    return root, database
