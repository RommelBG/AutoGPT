"""Backend mémoire réel basé sur ``pymem`` (Windows + EU5 lancé).

Ce module n'est importé qu'à la demande : il échoue proprement avec une
``ImportError`` si ``pymem`` n'est pas installé (cas des environnements de
développement non-Windows), ce qui déclenche le repli sur ``MockMemoryBackend``.
"""

from __future__ import annotations

from .backend import MemoryBackend

try:
    import pymem  # type: ignore
    import pymem.pattern  # type: ignore
    import pymem.process  # type: ignore
except ImportError as exc:  # pragma: no cover - dépend de la plateforme
    raise ImportError("pymem requis pour PymemBackend") from exc


class PymemBackend(MemoryBackend):
    """Lecture mémoire d'un processus via pymem."""

    available = True

    def __init__(self, process_name: str) -> None:
        self.process_name = process_name
        self._pm: "pymem.Pymem | None" = None
        self._module_base = 0

    def attach(self) -> bool:  # pragma: no cover - nécessite Windows + jeu
        try:
            self._pm = pymem.Pymem(self.process_name)
            module = pymem.process.module_from_name(
                self._pm.process_handle, self.process_name
            )
            self._module_base = module.lpBaseOfDll if module else self._pm.base_address
            return True
        except Exception:
            self._pm = None
            return False

    def module_base(self) -> int:  # pragma: no cover
        return self._module_base

    def read_bytes(self, address: int, size: int) -> bytes:  # pragma: no cover
        assert self._pm is not None, "backend non attaché"
        return self._pm.read_bytes(address, size)

    def scan_value(self, raw: bytes) -> list[int]:  # pragma: no cover
        """Scan AOB de toute la mémoire du processus pour la séquence ``raw``."""
        assert self._pm is not None, "backend non attaché"
        # Échappe chaque octet en motif AOB exact ("AA BB CC ...").
        pattern = " ".join(f"{b:02x}" for b in raw).encode()
        results: list[int] = []
        try:
            addr = pymem.pattern.pattern_scan_module(
                self._pm.process_handle, self.process_name, pattern
            )
            if addr:
                results.append(addr)
        except Exception:
            pass
        return results

    def resolve_pointer_chain(self, base: int, offsets: list[int]) -> int:  # pragma: no cover
        """Résout une chaîne de pointeurs (base -> +offsets) vers l'adresse finale."""
        assert self._pm is not None, "backend non attaché"
        addr = base
        for off in offsets[:-1]:
            addr = self._pm.read_longlong(addr + off)
        return addr + (offsets[-1] if offsets else 0)

    def close(self) -> None:  # pragma: no cover
        if self._pm is not None:
            try:
                self._pm.close_process()
            except Exception:
                pass
            self._pm = None
