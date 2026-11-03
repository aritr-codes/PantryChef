"""Input guard for the pack builder (ADR 0003, ARCHITECTURE section 3).

``guarded_build`` turns on a deny-by-default read policy for the current thread of control.
While it is on, the build may read only:

- files on the hash allow-list,
- the interpreter, site-packages and the repo's own code,
- system files (OS and libraries),
- files it wrote itself into ``write_dir``.

It may write only into ``write_dir`` (and ``__pycache__``). It may not start a process, open
a network socket or load a native library. This is a tripwire for mistakes, not a sandbox: a
C library that calls ``fopen`` directly does not raise an audit event and escapes it.

Python audit hooks cannot be removed. The module installs one hook for the process, and a
``ContextVar`` switches it on and off.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_CODE_SUFFIXES = {".py", ".pyc", ".pyd", ".so", ".dll", ".typed", ".pyi"}
_DENIED_EVENTS = {
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "socket.connect",
    "socket.bind",
    "ctypes.dlopen",
    "ctypes.cdata",
}


class GuardViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class _State:
    allowed_reads: frozenset[str]
    write_dir: str
    code_roots: tuple[str, ...]
    system_roots: tuple[str, ...]


_state: ContextVar[_State | None] = ContextVar("pack_guard_state", default=None)
_installed = False


def _norm(path: str | bytes | os.PathLike) -> str:
    return os.path.normcase(os.path.realpath(os.fsdecode(path)))


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def _system_roots() -> tuple[str, ...]:
    roots = [sys.prefix, sys.base_prefix, sys.exec_prefix, sysconfig.get_paths()["stdlib"]]
    if os.name == "nt":
        roots.append(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    else:
        roots += ["/usr", "/lib", "/lib64", "/etc", "/proc", "/sys", "/dev"]
    return tuple(_norm(r) for r in roots if r)


def _wants_write(mode: object, flags: object) -> bool:
    if isinstance(flags, int) and flags & _WRITE_FLAGS:
        return True
    return isinstance(mode, str) and any(c in mode for c in "wax+")


def _check_open(state: _State, path: object, mode: object, flags: object) -> None:
    if isinstance(path, int):  # an already open file descriptor
        return
    p = _norm(path)
    if _wants_write(mode, flags):
        if _under(p, state.write_dir) or p.endswith(".pyc"):
            return
        raise GuardViolation(f"build may not write outside the output folder: {p}")
    if (
        p in state.allowed_reads
        or _under(p, state.write_dir)
        or any(_under(p, r) for r in state.system_roots)
        or (Path(p).suffix in _CODE_SUFFIXES and any(_under(p, r) for r in state.code_roots))
    ):
        return
    raise GuardViolation(f"build opened a file outside the allow-list: {p}")


def _hook(event: str, args: tuple) -> None:
    state = _state.get()
    if state is None:
        return
    if event == "open":
        _check_open(
            state, args[0], args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None
        )
    elif event in _DENIED_EVENTS:
        raise GuardViolation(f"build may not use {event}")


@contextmanager
def guarded_build(
    allowed_reads: Iterable[str | Path], write_dir: str | Path, code_roots: Iterable[str | Path]
) -> Iterator[None]:
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True
    state = _State(
        allowed_reads=frozenset(_norm(p) for p in allowed_reads),
        write_dir=_norm(write_dir),
        code_roots=tuple(_norm(r) for r in code_roots),
        system_roots=_system_roots(),
    )
    token = _state.set(state)
    try:
        yield
    finally:
        _state.reset(token)
