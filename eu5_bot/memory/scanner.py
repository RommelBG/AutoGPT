"""Scanner mémoire (PHASE 1 — scan & cartographie).

Le scan est un **scan différentiel multi-passes**, la technique éprouvée des
outils type Cheat Engine :

    1. ``first_scan(valeur)``  → toutes les adresses contenant la valeur connue.
    2. La valeur évolue dans le jeu (le temps passe, le trésor change…).
    3. ``next_scan(nouvelle_valeur)`` → ne conserve, parmi les candidats, que ceux
       qui valent désormais la nouvelle valeur.
    4. On répète jusqu'à isoler une adresse unique.

Cette approche élimine naturellement les milliers de faux candidats qu'un scan
de valeur unique renvoie sur un vrai processus. Pour chaque champ isolé, on
dérive une **signature AOB** des octets voisins (résistance aux patchs) et un
offset relatif au module, puis on sérialise le tout dans une ``MemoryMap`` JSON
(cache + rescan forcé).

Sources de valeurs successives :
    - Hors-ligne / tests : le ``MockMemoryBackend`` fournit un ``value_provider``
      (lecture directe) et un ``settle`` (avance du temps simulé).
    - En jeu réel : ``value_provider`` est alimenté par calibration — typiquement
      la valeur affichée à l'écran, saisie via l'interface entre deux passes,
      ``settle`` étant une simple attente que le jeu fasse évoluer la valeur.
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

_SIZE = {"i32": 4, "i64": 8, "f32": 4, "f64": 8}

# Type des valeurs successives d'un champ et fonction provoquant un changement.
ValueProvider = Callable[[str], "float | int | None"]
SettleFn = Callable[[], None]
ProgressFn = Callable[[str, int, int], None]


def _encode(value: float | int, value_type: str) -> bytes:
    return {
        "i32": lambda v: struct.pack("<i", int(v)),
        "i64": lambda v: struct.pack("<q", int(v)),
        "f32": lambda v: struct.pack("<f", float(v)),
        "f64": lambda v: struct.pack("<d", float(v)),
    }[value_type](value)


def _decode(raw: bytes, value_type: str) -> float | int:
    return struct.unpack({"i32": "<i", "i64": "<q", "f32": "<f", "f64": "<d"}[value_type], raw)[0]


class MemoryScanner:
    """Découvre les adresses mémoire par scan différentiel et produit/charge une
    ``MemoryMap``."""

    def __init__(self, backend: MemoryBackend, process_name: str = "eu5.exe") -> None:
        self.backend = backend
        self.process_name = process_name

    # ------------------------------------------------------------------ #
    # Primitives de scan différentiel
    # ------------------------------------------------------------------ #
    def first_scan(self, value: float | int, value_type: str) -> list[int]:
        """Première passe : toutes les adresses contenant ``value``."""
        return self.backend.scan_value(_encode(value, value_type))

    def next_scan(
        self,
        candidates: list[int],
        value: float | int,
        value_type: str,
        tolerance: float = 0.0,
    ) -> list[int]:
        """Passe suivante : filtre ``candidates`` à ceux valant ``value``.

        ``tolerance`` > 0 autorise un écart (utile pour les flottants dont la
        valeur affichée diffère légèrement de la valeur stockée).
        """
        size = _SIZE[value_type]
        kept: list[int] = []
        for addr in candidates:
            data = self.backend.read_bytes(addr, size)
            if len(data) != size:
                continue
            if tolerance <= 0:
                if data == _encode(value, value_type):
                    kept.append(addr)
            else:
                try:
                    if abs(_decode(data, value_type) - value) <= tolerance:
                        kept.append(addr)
                except struct.error:
                    continue
        return kept

    def scan_field(
        self,
        field: str,
        value_type: str,
        reference: float | int | None,
        value_provider: ValueProvider | None,
        settle: SettleFn | None,
        max_passes: int,
        tolerance: float = 0.0,
    ) -> list[int]:
        """Isole l'adresse d'un champ par scan différentiel.

        Renvoie la liste des candidats survivants (idéalement un seul).
        """

        def current() -> float | int | None:
            if value_provider is not None:
                v = value_provider(field)
                if v is not None:
                    return v
            return reference

        val = current()
        if val is None:
            return []

        candidates = self.first_scan(val, value_type)
        passes = 1
        prev_val = val
        while len(candidates) > 1 and passes < max_passes:
            if settle is None:
                break  # aucun moyen de faire évoluer la valeur : on s'arrête
            settle()
            new_val = current()
            if new_val is None:
                break
            candidates = self.next_scan(candidates, new_val, value_type, tolerance)
            # Si la valeur n'a pas bougé, une passe de plus ne réduira rien.
            if new_val == prev_val:
                break
            prev_val = new_val
            passes += 1
        return candidates

    # ------------------------------------------------------------------ #
    # API publique
    # ------------------------------------------------------------------ #
    def scan(
        self,
        reference_values: dict[str, float | int] | None = None,
        value_provider: ValueProvider | None = None,
        settle: SettleFn | None = None,
        progress: ProgressFn | None = None,
        max_passes: int = 8,
        tolerance: float = 0.0,
    ) -> MemoryMap:
        """Scan complet : localise chaque champ et construit la carte mémoire.

        ``reference_values`` : valeurs d'ancrage par champ (calibration).
        ``value_provider``   : renvoie la valeur courante d'un champ (passe N).
        ``settle``           : provoque/attend un changement entre deux passes.
        Sur backend mock, ``value_provider`` et ``settle`` sont fournis
        automatiquement si non précisés.
        """
        refs = reference_values or {}
        if value_provider is None or settle is None:
            auto_provider, auto_settle = self._mock_helpers()
            value_provider = value_provider or auto_provider
            settle = settle or auto_settle

        mmap = MemoryMap(
            process_name=self.process_name,
            module_base=self.backend.module_base(),
        )
        base = self.backend.module_base()
        total = len(SCAN_PLAN)
        for i, (field, vtype) in enumerate(SCAN_PLAN.items(), start=1):
            candidates = self.scan_field(
                field, vtype, refs.get(field), value_provider, settle, max_passes, tolerance
            )
            if candidates:
                addr = candidates[0]
                confidence = 1.0 if len(candidates) == 1 else max(0.0, 1.0 - (len(candidates) - 1) * 0.2)
                mmap.signatures[field] = MemorySignature(
                    field=field,
                    address=addr,
                    offsets=[addr - base],
                    pattern=self._signature_around(addr),
                    value_type=vtype,
                    candidates=candidates[:8],
                    confidence=round(confidence, 3),
                )
            if progress:
                progress(field, i, total)
        return mmap

    def load_or_scan(
        self,
        path,
        force: bool = False,
        progress: ProgressFn | None = None,
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
    def _mock_helpers(self) -> tuple[ValueProvider | None, SettleFn | None]:
        """Pour le backend mock : provider (lecture directe) + settle (advance)."""
        backend = self.backend
        if isinstance(backend, MockMemoryBackend):

            def provider(field: str) -> float | int | None:
                addr = backend.address_of(field)
                if not addr:
                    return None
                return backend.read_typed(addr, backend.type_of(field))

            def settle() -> None:
                backend.advance(90.0)  # avance d'environ 90 s de jeu simulé

            return provider, settle
        return None, None

    def _signature_around(self, address: int, span: int = 8) -> str:
        """Construit une signature AOB des octets voisins (résistance aux patchs)."""
        data = self.backend.read_bytes(address - span, span * 2)
        if not data:
            return ""
        return " ".join(f"{b:02x}" for b in data)
