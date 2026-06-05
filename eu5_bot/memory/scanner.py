"""Scanner mémoire (PHASE 1 — scan & cartographie).

Au premier lancement, ``MemoryScanner`` parcourt le processus EU5 pour localiser
les adresses des champs économiques pertinents, puis sérialise le résultat dans
une ``MemoryMap`` JSON. Aux lancements suivants, la carte est rechargée depuis le
cache. Un "rescan forcé" est exposé pour reconstruire la carte après une mise à
jour du jeu.

Technique : pour chaque champ, on connaît une valeur courante de référence
(fournie par l'interface lors d'une calibration, ou détectée heuristiquement) ;
on scanne la mémoire pour cette valeur encodée, puis on retient l'adresse et on
en dérive une *signature dynamique* (octets voisins) afin de re-localiser
l'adresse même si elle se déplace après un patch.
"""

from __future__ import annotations

import struct
from typing import Callable

from ..models import MemoryMap, MemorySignature
from .backend import MemoryBackend, MockMemoryBackend


# Champs recherchés et leur type binaire attendu.
SCAN_PLAN: dict[str, str] = {
    "tresor": "f64",
    "revenu_taxes": "f32",
    "revenu_production": "f32",
    "revenu_commerce": "f32",
    "revenu_sujets": "f32",
    "depenses_mensuelles": "f32",
    "dettes": "f32",
    "inflation": "f32",
    "stabilite": "i32",
    "manpower": "i32",
    "score_puissance": "i32",
    "menace_militaire": "i32",
}


def _encode(value: float | int, value_type: str) -> bytes:
    return {
        "i32": lambda v: struct.pack("<i", int(v)),
        "i64": lambda v: struct.pack("<q", int(v)),
        "f32": lambda v: struct.pack("<f", float(v)),
        "f64": lambda v: struct.pack("<d", float(v)),
    }[value_type](value)


class MemoryScanner:
    """Découvre les adresses mémoire et produit/charge une ``MemoryMap``."""

    def __init__(self, backend: MemoryBackend, process_name: str = "eu5.exe") -> None:
        self.backend = backend
        self.process_name = process_name

    # ------------------------------------------------------------------ #
    # API publique
    # ------------------------------------------------------------------ #
    def scan(
        self,
        reference_values: dict[str, float | int] | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> MemoryMap:
        """Scan complet : localise chaque champ et construit la carte mémoire.

        ``reference_values`` : valeurs connues servant d'ancrage au scan par
        valeur. Pour le backend mock, elles sont déduites automatiquement.
        ``progress(field, done, total)`` : callback de progression (interface).
        """
        mmap = MemoryMap(
            process_name=self.process_name,
            module_base=self.backend.module_base(),
        )
        refs = reference_values or self._auto_reference_values()
        total = len(SCAN_PLAN)
        for i, (field, vtype) in enumerate(SCAN_PLAN.items(), start=1):
            sig = self._locate(field, vtype, refs.get(field))
            if sig is not None:
                mmap.signatures[field] = sig
            if progress:
                progress(field, i, total)
        return mmap

    def load_or_scan(
        self,
        path,
        force: bool = False,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> tuple[MemoryMap, str]:
        """Charge la carte depuis ``path``, ou la (re)scanne si absente/forcée.

        Renvoie ``(carte, statut)`` où statut ∈ {"chargé", "scanné"}.
        """
        if not force:
            cached = MemoryMap.load(path)
            if cached is not None and cached.signatures:
                return cached, "chargé"
        mmap = self.scan(progress=progress)
        mmap.save(path)
        return mmap, "scanné"

    # ------------------------------------------------------------------ #
    # Internes
    # ------------------------------------------------------------------ #
    def _auto_reference_values(self) -> dict[str, float | int]:
        """Pour le backend mock : lit directement les valeurs de référence."""
        if isinstance(self.backend, MockMemoryBackend):
            refs: dict[str, float | int] = {}
            for field, vtype in SCAN_PLAN.items():
                addr = self.backend.address_of(field)
                if addr:
                    refs[field] = self.backend.read_typed(addr, vtype)
            return refs
        return {}

    def _locate(
        self, field: str, value_type: str, ref: float | int | None
    ) -> MemorySignature | None:
        """Localise un champ par scan de sa valeur de référence encodée."""
        if ref is None:
            return None
        raw = _encode(ref, value_type)
        hits = self.backend.scan_value(raw)
        if not hits:
            return None
        address = hits[0]  # premier candidat ; un vrai scan affinerait par diff
        pattern = self._signature_around(address)
        return MemorySignature(
            field=field,
            address=address,
            offsets=[address - self.backend.module_base()],
            pattern=pattern,
            value_type=value_type,
        )

    def _signature_around(self, address: int, span: int = 8) -> str:
        """Construit une signature AOB des octets voisins (résistance aux patchs)."""
        try:
            data = self.backend.read_bytes(address - span, span * 2)
        except Exception:
            return ""
        return " ".join(f"{b:02x}" for b in data)
