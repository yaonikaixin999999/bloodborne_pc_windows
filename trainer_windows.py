# Windows port modifications by yaonikaixin999999, 2026-10-06.
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reversible, fingerprint-gated trainer for this project's Windows runtime.

Hook locations and field semantics were researched from Shiningami's Bloodborne
1.09 cheats in shadPS4's cheat collection. The implementation allocates its own
ASLR-aware trampolines; it does not use the original cheat's fixed code caves.
Only the project's bb-probe executables are accepted. No game files or saves
are read or modified. Private API injection is provided for synthetic tests.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import struct
import sys
import time
from typing import Iterable


class TrainerError(Exception):
    """An unsupported process, busy hook, or failed Windows operation."""


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    path: str


@dataclass(frozen=True)
class Hook:
    offset: int
    original: bytes


HOOKS = {
    "health": Hook(0x18F78B1, bytes.fromhex("8B88F8000000")),
    "stamina": Hook(0x18F78DB, bytes.fromhex("8B8034010000")),
    "echoes": Hook(0x190029B, bytes.fromhex("898A94000000")),
    # The preceding JBE targets 0x14D9559. Hooking 0x14D9556, as the original
    # cheat does, would leave that branch jumping into the middle of a rel32
    # displacement. Move the hook to the common destination and relocate the
    # following LEA as well, giving eight whole instruction bytes.
    "items": Hook(0x14D9559, bytes.fromhex("44896308488D7DB8")),
}
FEATURES = frozenset(HOOKS)
CAVE_SIZE = 4096
SLOT_SIZE = 64
CODE_SIZE = SLOT_SIZE * len(HOOKS)
MEM_COMMIT, MEM_RESERVE, MEM_RELEASE = 0x1000, 0x2000, 0x8000
MEM_PRIVATE, MEM_FREE = 0x20000, 0x10000
PAGE_READWRITE, PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE = 0x04, 0x20, 0x40
PAGE_GUARD, PAGE_NOACCESS = 0x100, 0x01
# 冻结成 exe 后 __file__ 不再是源码路径：数据根取 exe 所在目录，
# 这样与 bb-probe.exe 放在一起时能直接匹配进程路径。
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
SUPPORTED_PATHS = (ROOT / "dist/windows/bb-probe.exe", ROOT / "out/windows/bin/bb-probe.exe",
                   ROOT / "bb-probe.exe")


def _normal_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _rel32_jump(source: int, target: int, size: int = 5) -> bytes:
    distance = target - (source + 5)
    if size < 5 or not -(1 << 31) <= distance < (1 << 31):
        raise TrainerError("无法分配安全的近距离跳转地址。")
    return b"\xe9" + struct.pack("<i", distance) + b"\x90" * (size - 5)


def _trampoline(feature: str, address: int, return_address: int,
                echoes: int, items: int) -> bytes:
    if feature == "health":
        body = bytes.fromhex("8B88FC0000008988F8000000")
    elif feature == "stamina":
        # EAX writes zero-extend RAX. Keep the object pointer until the field
        # write is complete, preserve RCX, then reproduce the original load.
        body = bytes.fromhex("518B8838010000898834010000598B8034010000")
    elif feature == "echoes":
        body = b"\xb9" + struct.pack("<I", echoes) + bytes.fromhex("898A94000000")
    elif feature == "items":
        body = bytes.fromhex("41BC") + struct.pack("<I", items) + bytes.fromhex("44896308488D7DB8")
    else:
        raise TrainerError("未知的修改项目。")
    return body + _rel32_jump(address + len(body), return_address)


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]


class _MemoryInfo(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]


@dataclass(frozen=True)
class MemoryRegion:
    base: int
    allocation_base: int
    size: int
    state: int
    protect: int
    kind: int


class WindowsAPI:
    """Small WinAPI adapter. Tests may substitute this entire interface."""

    def __init__(self):
        if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise TrainerError("修改器需要 64 位 Windows 和 64 位 Python。")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        declarations = {
            "OpenProcess": (wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
            "CloseHandle": (wintypes.BOOL, [wintypes.HANDLE]),
            "ReadProcessMemory": (wintypes.BOOL, [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]),
            "WriteProcessMemory": (wintypes.BOOL, [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]),
            "VirtualQueryEx": (ctypes.c_size_t, [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MemoryInfo), ctypes.c_size_t]),
            "VirtualAllocEx": (ctypes.c_void_p, [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]),
            "VirtualFreeEx": (wintypes.BOOL, [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]),
            "VirtualProtectEx": (wintypes.BOOL, [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]),
            "FlushInstructionCache": (wintypes.BOOL, [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t]),
            "GetExitCodeProcess": (wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]),
            "QueryFullProcessImageNameW": (wintypes.BOOL, [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]),
            "CreateToolhelp32Snapshot": (wintypes.HANDLE, [wintypes.DWORD, wintypes.DWORD]),
            "Process32FirstW": (wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]),
            "Process32NextW": (wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]),
            "Thread32First": (wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]),
            "Thread32Next": (wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]),
            "OpenThread": (wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
            "SuspendThread": (wintypes.DWORD, [wintypes.HANDLE]),
            "ResumeThread": (wintypes.DWORD, [wintypes.HANDLE]),
            "GetThreadContext": (wintypes.BOOL, [wintypes.HANDLE, ctypes.c_void_p]),
            "CreateMutexW": (wintypes.HANDLE, [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]),
            "WaitForSingleObject": (wintypes.DWORD, [wintypes.HANDLE, wintypes.DWORD]),
            "ReleaseMutex": (wintypes.BOOL, [wintypes.HANDLE]),
        }
        for name, (restype, argtypes) in declarations.items():
            function = getattr(self.kernel, name)
            function.restype, function.argtypes = restype, argtypes

    @staticmethod
    def _error(operation: str) -> TrainerError:
        return TrainerError(f"Windows 操作失败：{operation}（错误 {ctypes.get_last_error()}）。")

    def close_handle(self, handle):
        if handle and not self.kernel.CloseHandle(handle):
            raise self._error("CloseHandle")

    def open_process(self, pid: int):
        handle = self.kernel.OpenProcess(0x100000 | 0x1000 | 0x0400 | 0x10 | 0x20 | 0x08, False, pid)
        if not handle:
            raise self._error("OpenProcess")
        return handle

    def process_path(self, handle) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        count = wintypes.DWORD(len(buffer))
        if not self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(count)):
            raise self._error("QueryFullProcessImageNameW")
        return buffer.value

    def processes(self) -> list[ProcessInfo]:
        snapshot = self.kernel.CreateToolhelp32Snapshot(0x02, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise self._error("CreateToolhelp32Snapshot")
        result = []
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = self.kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while found:
                handle = self.kernel.OpenProcess(0x1000, False, entry.th32ProcessID)
                if handle:
                    try:
                        result.append(ProcessInfo(int(entry.th32ProcessID), self.process_path(handle)))
                    except TrainerError:
                        pass  # A process may exit during enumeration.
                    finally:
                        self.close_handle(handle)
                found = self.kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            self.close_handle(snapshot)
        return result

    def is_alive(self, handle) -> bool:
        # A real exit code may be 259, so use the signaled process handle.
        status = self.kernel.WaitForSingleObject(handle, 0)
        if status == 0:
            return False
        if status == 0x102:
            return True
        raise self._error("WaitForSingleObject")

    def read(self, handle, address: int, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        count = ctypes.c_size_t()
        ok = self.kernel.ReadProcessMemory(handle, address, buffer, size, ctypes.byref(count))
        if not ok or count.value != size:
            raise self._error("ReadProcessMemory")
        return buffer.raw

    def write(self, handle, address: int, data: bytes):
        buffer = ctypes.create_string_buffer(data)
        count = ctypes.c_size_t()
        ok = self.kernel.WriteProcessMemory(handle, address, buffer, len(data), ctypes.byref(count))
        if not ok or count.value != len(data):
            raise self._error("WriteProcessMemory")

    def query(self, handle, address: int) -> MemoryRegion | None:
        info = _MemoryInfo()
        if not self.kernel.VirtualQueryEx(handle, address, ctypes.byref(info), ctypes.sizeof(info)):
            return None
        return MemoryRegion(int(info.BaseAddress or 0), int(info.AllocationBase or 0),
                            int(info.RegionSize), int(info.State), int(info.Protect), int(info.Type))

    def regions(self, handle):
        address = 0
        while address < 0x0000800000000000:
            region = self.query(handle, address)
            if region is None:
                break
            yield region
            next_address = region.base + region.size
            if next_address <= address:
                raise TrainerError("Windows 返回了无效的内存区间。")
            address = next_address

    def allocate_near(self, handle, lowest: int, highest: int) -> int:
        granularity = 65536
        cursor = max(granularity, (lowest + granularity - 1) & ~(granularity - 1))
        highest = min(highest, 0x00007FFFFFFF0000)
        while cursor <= highest:
            region = self.query(handle, cursor)
            if region is None:
                break
            if region.state == MEM_FREE:
                candidate = max(cursor, (region.base + granularity - 1) & ~(granularity - 1))
                end = min(highest + CAVE_SIZE, region.base + region.size)
                # Normally the first free reservation works; another allocator
                # can win the race between VirtualQueryEx and VirtualAllocEx.
                while candidate <= highest and candidate + CAVE_SIZE <= end:
                    result = self.kernel.VirtualAllocEx(handle, candidate, CAVE_SIZE,
                                                       MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE)
                    if result:
                        return int(result)
                    candidate += granularity
            next_cursor = region.base + region.size
            if next_cursor <= cursor:
                break
            cursor = (next_cursor + granularity - 1) & ~(granularity - 1)
        raise TrainerError("未找到可用的近距离修改器内存；请关闭修改器并重试。")

    def free(self, handle, address: int):
        if not self.kernel.VirtualFreeEx(handle, address, 0, MEM_RELEASE):
            raise self._error("VirtualFreeEx")

    def protect(self, handle, address: int, size: int, protection: int) -> int:
        old = wintypes.DWORD()
        if not self.kernel.VirtualProtectEx(handle, address, size, protection, ctypes.byref(old)):
            raise self._error("VirtualProtectEx")
        return int(old.value)

    def flush(self, handle, address: int, size: int):
        if not self.kernel.FlushInstructionCache(handle, address, size):
            raise self._error("FlushInstructionCache")

    def acquire_owner(self, pid: int):
        ctypes.set_last_error(0)
        handle = self.kernel.CreateMutexW(None, True, f"Local\\BloodbornePcWindowsTrainer-{pid}")
        if not handle:
            raise self._error("CreateMutexW")
        if ctypes.get_last_error() == 183:
            # Reject an existing object even on the same thread: waiting on a
            # mutex already owned by that thread would recursively succeed.
            self.close_handle(handle)
            raise TrainerError("已有另一个修改器连接到这个游戏，请先关闭它。")
        return handle

    def release_owner(self, handle):
        try:
            if not self.kernel.ReleaseMutex(handle):
                raise self._error("ReleaseMutex")
        finally:
            self.close_handle(handle)

    def _thread_ids(self, pid: int) -> set[int]:
        snapshot = self.kernel.CreateToolhelp32Snapshot(0x04, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise self._error("CreateToolhelp32Snapshot")
        result = set()
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = self.kernel.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == pid:
                    result.add(int(entry.th32ThreadID))
                found = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            self.close_handle(snapshot)
        return result

    def suspend_threads(self, pid: int) -> list[tuple[int, int]]:
        suspended = []
        seen = set()
        try:
            for _ in range(4):
                missing = self._thread_ids(pid) - seen
                if not missing:
                    if not suspended:
                        raise TrainerError("游戏进程已经退出或没有可暂停的线程。")
                    return suspended
                for tid in sorted(missing):
                    handle = self.kernel.OpenThread(0x02 | 0x08 | 0x40, False, tid)
                    if not handle:
                        # Treat an unobservable thread as unsafe, even if it
                        # may have exited between snapshot and OpenThread.
                        raise self._error("OpenThread")
                    if self.kernel.SuspendThread(handle) == 0xFFFFFFFF:
                        self.close_handle(handle)
                        raise self._error("SuspendThread")
                    suspended.append((handle, 0))
                    # Win64 CONTEXT is 1232 bytes, aligned to 16. ContextFlags
                    # is at 48 and Rip at 248 in the documented x64 layout.
                    buffer = ctypes.create_string_buffer(1232 + 15)
                    address = (ctypes.addressof(buffer) + 15) & ~15
                    ctypes.c_uint32.from_address(address + 48).value = 0x00100001
                    if not self.kernel.GetThreadContext(handle, address):
                        raise self._error("GetThreadContext")
                    rip = ctypes.c_uint64.from_address(address + 248).value
                    suspended[-1] = (handle, int(rip))
                    seen.add(tid)
            raise TrainerError("游戏线程正在变化，暂时无法安全修改，请稍后重试。")
        except BaseException:
            self.resume_threads(suspended)
            raise

    def resume_threads(self, suspended):
        errors = []
        for handle, _ in reversed(suspended):
            try:
                if self.kernel.ResumeThread(handle) == 0xFFFFFFFF:
                    errors.append(self._error("ResumeThread"))
            finally:
                try:
                    self.close_handle(handle)
                except TrainerError as error:
                    errors.append(error)
        if errors:
            raise errors[0]


def discover_games(*, _api=None, _allowed_paths=None) -> list[ProcessInfo]:
    if _allowed_paths is not None and _api is None:
        raise TrainerError("自定义进程路径仅用于隔离测试。")
    api = _api if _api is not None else WindowsAPI()
    paths = {_normal_path(path) for path in (_allowed_paths or SUPPORTED_PATHS)}
    return [process for process in api.processes() if _normal_path(process.path) in paths]


class TrainerSession:
    """Own one process connection and all reversible patches in that session."""

    @classmethod
    def connect(cls, pid: int, *, _api=None, _allowed_paths=None):
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise TrainerError("无效的游戏进程编号。")
        if _allowed_paths is not None and _api is None:
            raise TrainerError("自定义进程路径仅用于隔离测试。")
        api = _api if _api is not None else WindowsAPI()
        handle = api.open_process(pid)
        owner = None
        try:
            path = api.process_path(handle)
            allowed = {_normal_path(p) for p in (_allowed_paths or SUPPORTED_PATHS)}
            if _normal_path(path) not in allowed:
                raise TrainerError("仅支持此项目的 Windows 游戏进程，请通过本项目启动器运行游戏。")
            if not api.is_alive(handle):
                raise TrainerError("游戏进程已退出。")
            owner = api.acquire_owner(pid)
            matches, seen = [], set()
            minimum = max(h.offset + len(h.original) for h in HOOKS.values())
            for region in api.regions(handle):
                if region.state != MEM_COMMIT or region.kind != MEM_PRIVATE:
                    continue
                base = region.allocation_base
                if not base or base in seen or region.base + region.size - base < minimum:
                    continue
                seen.add(base)
                try:
                    if all(api.read(handle, base + hook.offset, len(hook.original)) == hook.original
                           for hook in HOOKS.values()):
                        matches.append(base)
                except TrainerError:
                    continue
            if len(matches) != 1:
                raise TrainerError("游戏版本或代码不匹配。仅支持已验证的 1.09 原始代码；请关闭其他修改器后重试。")
            return cls(api, handle, owner, pid, matches[0])
        except BaseException:
            try:
                if owner is not None:
                    api.release_owner(owner)
            finally:
                api.close_handle(handle)
            raise

    def __init__(self, api, handle, owner, pid: int, image_base: int):
        self._api, self._handle, self._owner = api, handle, owner
        self.pid, self.image_base = pid, image_base
        self.enabled: set[str] = set()
        self._cave = 0
        self._cave_code = b""
        self._closed = False
        self._faulted = False
        self._echoes, self._items = 1000000, 20

    def is_alive(self) -> bool:
        return not self._closed and self._api.is_alive(self._handle)

    def _require_live(self):
        if self._closed:
            raise TrainerError("修改器连接已经关闭。")
        if not self.is_alive():
            raise TrainerError("游戏进程已退出，请重新连接。")

    def _hook_bytes(self, feature: str, enabled: set[str]) -> bytes:
        hook = HOOKS[feature]
        if feature not in enabled:
            return hook.original
        slot = list(HOOKS).index(feature) * SLOT_SIZE
        return _rel32_jump(self.image_base + hook.offset, self._cave + slot, len(hook.original))

    def _make_code(self, echoes: int, items: int) -> bytes:
        code = bytearray(b"\xcc" * CODE_SIZE)
        for index, (feature, hook) in enumerate(HOOKS.items()):
            slot = index * SLOT_SIZE
            body = _trampoline(feature, self._cave + slot,
                               self.image_base + hook.offset + len(hook.original), echoes, items)
            if len(body) > SLOT_SIZE:
                raise TrainerError("修改器代码超出预留空间。")
            code[slot:slot + len(body)] = body
        return bytes(code)

    @contextmanager
    def _pause_safely(self):
        for attempt in range(12):
            self._require_live()
            suspended = self._api.suspend_threads(self.pid)
            ranges = [(self.image_base + h.offset, self.image_base + h.offset + len(h.original))
                      for h in HOOKS.values()]
            if self._cave:
                ranges.append((self._cave, self._cave + CAVE_SIZE))
            busy = any(start <= rip < end for _, rip in suspended for start, end in ranges)
            if busy:
                self._api.resume_threads(suspended)
                if attempt == 11:
                    raise TrainerError("游戏正在执行修改区域，请稍后重试。")
                time.sleep(0.015)
                continue
            try:
                yield
            finally:
                self._api.resume_threads(suspended)
            return

    def _write_protected(self, address: int, data: bytes):
        # Each owned range is entirely within one Windows page; otherwise one
        # VirtualProtectEx result would not describe every original protection.
        if address // 4096 != (address + len(data) - 1) // 4096:
            raise TrainerError("修改范围跨越内存页，已拒绝修改。")
        old = self._api.protect(self._handle, address, len(data), PAGE_EXECUTE_READWRITE)
        try:
            self._api.write(self._handle, address, data)
            if self._api.read(self._handle, address, len(data)) != data:
                raise TrainerError("修改后的内存校验失败。")
            self._api.flush(self._handle, address, len(data))
        finally:
            self._api.protect(self._handle, address, len(data), old)

    def _validate_ownership(self):
        for feature, hook in HOOKS.items():
            expected = self._hook_bytes(feature, self.enabled)
            if self._api.read(self._handle, self.image_base + hook.offset, len(expected)) != expected:
                raise TrainerError("游戏代码已被其他程序修改；为避免覆盖其他修改，操作已取消。")
        if self._cave and self._cave_code:
            if self._api.read(self._handle, self._cave, len(self._cave_code)) != self._cave_code:
                raise TrainerError("修改器预留代码已变化，操作已取消。")

    def apply(self, enabled: Iterable[str], echoes: int = 1000000, items: int = 20):
        try:
            selected = set(enabled)
        except (TypeError, ValueError) as error:
            raise TrainerError("无效的修改项目。") from error
        if not selected <= FEATURES:
            raise TrainerError("未知的修改项目。")
        if isinstance(echoes, bool) or not isinstance(echoes, int) or not 0 <= echoes <= 99999999:
            raise TrainerError("血之回响必须为 0 到 99999999 的整数。")
        if isinstance(items, bool) or not isinstance(items, int) or not 1 <= items <= 99:
            raise TrainerError("物品数量必须为 1 到 99 的整数。")
        self._require_live()
        if self._faulted:
            raise TrainerError("上一次回滚未能完成，请关闭游戏后再重新连接。")
        if selected == self.enabled and echoes == self._echoes and items == self._items:
            # Even an apparent no-op must detect lost ownership.
            self._validate_ownership()
            return
        if not selected and not self._cave:
            self._validate_ownership()
            self._echoes, self._items = echoes, items
            return
        new_cave = False
        if not self._cave:
            addresses = [self.image_base + hook.offset for hook in HOOKS.values()]
            # Conservatively intersect both outward and return rel32 ranges,
            # allowing for all code slots and the longest trampoline.
            lowest = max(addresses) - (1 << 31) + CAVE_SIZE
            highest = min(addresses) + (1 << 31) - CAVE_SIZE
            self._cave = self._api.allocate_near(self._handle, lowest, highest)
            new_cave = True
        try:
            code = self._make_code(echoes, items)
            with self._pause_safely():
                self._validate_ownership()
                writes = [(self._cave, code)]
                writes.extend((self.image_base + hook.offset, self._hook_bytes(feature, selected))
                              for feature, hook in HOOKS.items()
                              if feature in selected or feature in self.enabled)
                undo = []
                try:
                    # Mark an attempted write for rollback before writing:
                    # WriteProcessMemory can fail after a partial transfer.
                    for address, data in writes:
                        original = self._api.read(self._handle, address, len(data))
                        if original == data:
                            continue
                        undo.append((address, original))
                        self._write_protected(address, data)
                    self._api.protect(self._handle, self._cave, CAVE_SIZE, PAGE_EXECUTE_READ)
                except BaseException as error:
                    rollback_errors = []
                    for address, original in reversed(undo):
                        try:
                            self._write_protected(address, original)
                        except BaseException as rollback_error:
                            rollback_errors.append(rollback_error)
                    if rollback_errors:
                        self._faulted = True
                        raise TrainerError("修改失败且回滚未能完成；请关闭游戏后重新连接。") from error
                    raise
                self.enabled = selected
                self._cave_code = code
                self._echoes, self._items = echoes, items
        except BaseException:
            if new_cave and not self._faulted and not self.enabled:
                self._api.free(self._handle, self._cave)
                self._cave, self._cave_code = 0, b""
            raise

    def close(self):
        if self._closed:
            return
        if self.is_alive():
            if self._faulted:
                raise TrainerError("回滚未完成，请先关闭游戏，再关闭修改器连接。")
            self.apply(set(), self._echoes, self._items)
            # apply restored all branches while every thread was outside the
            # owned code. No thread can enter these caves after that point.
            if self._cave:
                self._api.free(self._handle, self._cave)
                self._cave, self._cave_code = 0, b""
        self.enabled.clear()
        self._closed = True
        try:
            self._api.release_owner(self._owner)
        finally:
            self._api.close_handle(self._handle)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
