"""Backend mémoire réel basé sur ``pymem`` (Windows + EU5 lancé).

Ce module n'est importé qu'à la demande : il échoue proprement avec une
``ImportError`` si ``pymem`` n'est pas installé (cas des environnements de
développement non-Windows), ce qui déclenche le repli sur ``MockMemoryBackend``.

Le scan complet repose sur ``enum_regions`` (énumération des régions committées
et lisibles via ``VirtualQueryEx``) ; la recherche de valeur elle-même est
fournie par l'implémentation partagée de ``MemoryBackend.scan_value`` qui lit
chaque région par blocs.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .backend import MemoryBackend

try:
    import pymem  # type: ignore
    import pymem.process  # type: ignore
except ImportError as exc:  # pragma: no cover - dépend de la plateforme
    raise ImportError("pymem requis pour PymemBackend") from exc


# Constantes Windows pour VirtualQueryEx.
_MEM_COMMIT = 0x1000
_PAGE_GUARD = 0x100
_PAGE_NOACCESS = 0x01
# Protections autorisant la lecture.
_READABLE = {
    0x02,  # PAGE_READONLY
    0x04,  # PAGE_READWRITE
    0x08,  # PAGE_WRITECOPY
    0x20,  # PAGE_EXECUTE_READ
    0x40,  # PAGE_EXECUTE_READWRITE
    0x80,  # PAGE_EXECUTE_WRITECOPY
}
_MAX_USERSPACE = 0x7FFFFFFFFFFF


class _MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wintypes.DWORD),
        ("__alignment1", wintypes.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("__alignment2", wintypes.DWORD),
    ]


class PymemBackend(MemoryBackend):
    """Lecture mémoire d'un processus via pymem."""

    available = True

    def __init__(self, process_name: str) -> None:
        self.process_name = process_name
        self._pm = None
        self._module_base = 0
        self._module_size = 0

    def attach(self) -> bool:  # pragma: no cover - nécessite Windows + jeu
        try:
            self._pm = pymem.Pymem(self.process_name)
            module = pymem.process.module_from_name(
                self._pm.process_handle, self.process_name
            )
            if module:
                self._module_base = module.lpBaseOfDll
                self._module_size = getattr(module, "SizeOfImage", 0)
            else:
                self._module_base = self._pm.base_address
            return True
        except Exception:
            self._pm = None
            return False

    def module_base(self) -> int:  # pragma: no cover
        return self._module_base

    def module_range(self) -> tuple[int, int]:  # pragma: no cover
        return (self._module_base, self._module_size)

    def enum_regions(self) -> list[tuple[int, int]]:  # pragma: no cover
        """Énumère les régions committées et lisibles du processus."""
        assert self._pm is not None, "backend non attaché"
        handle = self._pm.process_handle
        VirtualQueryEx = ctypes.windll.kernel32.VirtualQueryEx
        VirtualQueryEx.restype = ctypes.c_size_t
        mbi = _MEMORY_BASIC_INFORMATION64()
        size = ctypes.sizeof(mbi)
        regions: list[tuple[int, int]] = []
        addr = 0
        while addr < _MAX_USERSPACE:
            ret = VirtualQueryEx(handle, ctypes.c_ulonglong(addr), ctypes.byref(mbi), size)
            if not ret:
                break
            base = mbi.BaseAddress
            region_size = mbi.RegionSize
            if region_size == 0:
                break
            protect = mbi.Protect
            readable = (
                mbi.State == _MEM_COMMIT
                and not (protect & _PAGE_GUARD)
                and protect != _PAGE_NOACCESS
                and (protect & 0xFF) in _READABLE
            )
            if readable:
                regions.append((base, region_size))
            addr = base + region_size
        return regions

    def read_bytes(self, address: int, size: int) -> bytes:  # pragma: no cover
        assert self._pm is not None, "backend non attaché"
        try:
            return self._pm.read_bytes(address, size)
        except Exception:
            return b""  # région devenue illisible : ignorée par le scan

    # ``read_pointer``, ``build_pointer_index`` et ``resolve_chain`` sont fournis
    # par ``MemoryBackend`` (implémentation partagée basée sur ``read_bytes``).

    def close(self) -> None:  # pragma: no cover
        if self._pm is not None:
            try:
                self._pm.close_process()
            except Exception:
                pass
            self._pm = None
