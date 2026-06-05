"""Scan du tableau de provinces (structures contiguës en mémoire).

Les provinces sont stockées comme un tableau de structures de taille fixe
(``stride``). La découverte procède ainsi :

    1. Localiser, par scan de valeur, le champ ``developpement`` de deux
       provinces aux valeurs connues (calibration).
    2. En déduire ``base`` (1re structure) et ``stride`` (écart entre deux).
    3. Sonder vers l'avant pour déterminer ``count`` (fin du tableau quand la
       valeur n'est plus plausible).
    4. Pour chaque autre champ connu, déterminer son offset dans la structure en
       vérifiant sa cohérence sur une seconde province.
    5. Chercher une chaîne de pointeurs vers ``base`` pour la persistance.

Sources de calibration :
    - mock → ``backend.province_calibration()`` (oracle de test) ;
    - jeu réel → valeurs saisies via l'interface (développement de 2 provinces,
      etc.), exactement comme pour la calibration scalaire.
"""

from __future__ import annotations

from ..models import Province, ProvinceLayout
from .backend import MemoryBackend
from .pointers import PointerScanner
from .scanner import _encode

_MAX_STRIDE = 0x8000
_MAX_COUNT = 256


class ProvinceScanner:
    """Découvre la disposition mémoire du tableau de provinces."""

    def __init__(self, backend: MemoryBackend, pointer_scanner: PointerScanner | None = None) -> None:
        self.backend = backend
        self.pointer_scanner = pointer_scanner

    # ------------------------------------------------------------------ #
    def scan(
        self,
        calibration_values: dict[str, list],
        types: dict[str, str],
    ) -> ProvinceLayout | None:
        """Construit un ``ProvinceLayout`` à partir des valeurs de calibration."""
        devs = calibration_values.get("developpement")
        dtype = types.get("developpement", "i32")
        if not devs or len(devs) < 2:
            return None

        addr0_cands = self._locate(devs[0], dtype)
        addr1_cands = self._locate(devs[1], dtype)
        if not addr0_cands or not addr1_cands:
            return None

        # Choisit la paire (prov0, prov1) au stride positif plausible.
        base = stride = None
        for a0 in sorted(addr0_cands):
            for a1 in sorted(addr1_cands):
                d = a1 - a0
                if 0 < d <= _MAX_STRIDE:
                    base, stride = a0, d
                    break
            if stride:
                break
        if stride is None:
            return None

        layout = ProvinceLayout(base_address=base, stride=stride)
        layout.field_offsets["developpement"] = 0
        layout.field_types["developpement"] = dtype

        # Offsets des autres champs (vérifiés sur une 2e province).
        for fld, vals in calibration_values.items():
            if fld == "developpement" or not vals:
                continue
            vtype = types.get(fld, "i32")
            cands = self._locate(vals[0], vtype, within=(base, base + stride))
            off = self._consistent_offset(cands, base, stride, vals, vtype)
            if off is not None:
                layout.field_offsets[fld] = off
                layout.field_types[fld] = vtype

        layout.count = self._detect_count(base, stride, dtype)

        # Chaîne de pointeurs vers la base du tableau (persistance aux relances).
        if self.pointer_scanner is not None:
            chain = self.pointer_scanner.scan(base)
            if chain is not None:
                layout.pointer_chain = chain

        return layout

    # ------------------------------------------------------------------ #
    def _locate(self, value, vtype: str, within: tuple[int, int] | None = None) -> list[int]:
        hits = self.backend.scan_value(_encode(value, vtype))
        if within is not None:
            lo, hi = within
            hits = [h for h in hits if lo <= h < hi]
        return hits

    def _consistent_offset(self, cands, base, stride, vals, vtype) -> int | None:
        tol = 0.5 if vtype.startswith("f") else 0
        for c in sorted(cands):
            off = c - base
            if len(vals) >= 2:
                try:
                    v1 = self.backend.read_typed(base + stride + off, vtype)
                except Exception:
                    continue
                if abs(v1 - vals[1]) > tol:
                    continue
            return off
        return None

    def _detect_count(self, base, stride, dtype) -> int:
        count = 0
        for i in range(_MAX_COUNT):
            try:
                v = self.backend.read_typed(base + i * stride, dtype)
            except Exception:
                break
            plausible = (0 < v < 1e6) if isinstance(v, float) else (0 < v < 100000)
            if not plausible:
                break
            count += 1
        return count


def read_provinces(
    backend: MemoryBackend, layout: ProvinceLayout | None, module_base: int
) -> list[Province]:
    """Lit toutes les provinces via le layout (base résolue par pointeur si
    possible)."""
    if not layout or layout.count <= 0:
        return []
    base = layout.base_address
    if layout.pointer_chain is not None:
        resolved = backend.resolve_chain(module_base, layout.pointer_chain)
        if resolved:
            base = resolved

    provinces: list[Province] = []
    for i in range(layout.count):
        pbase = base + i * layout.stride

        def field(name: str, default=0):
            if name not in layout.field_offsets:
                return default
            return backend.read_typed(pbase + layout.field_offsets[name], layout.field_types[name])

        dev = int(field("developpement"))
        slots = int(field("slots_disponibles"))
        nb = int(field("nb_batiments"))
        provinces.append(
            Province(
                nom=f"Province {i + 1}",
                developpement=dev,
                slots_disponibles=slots,
                batiments=[f"bâtiment {k + 1}" for k in range(max(0, nb))],
            )
        )
    return provinces
