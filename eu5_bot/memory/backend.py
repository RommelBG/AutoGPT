"""Abstraction de l'accès mémoire du processus EU5.

Le reste du bot ne dépend que de l'interface ``MemoryBackend``. Deux
implémentations sont fournies :

    - ``PymemBackend``     : lecture réelle via ``pymem`` (Windows + jeu lancé),
      avec énumération des régions, scan de valeurs et index de pointeurs.
    - ``MockMemoryBackend``: simulation complète : un module + un tas, des
      pointeurs statiques (module → struct économique / tableau de provinces),
      des leurres figés, et ``relaunch()`` qui rejoue l'ASLR (les adresses
      absolues changent, les chaînes de pointeurs restent valides). Cela permet
      d'exercer et tester hors-ligne le scan différentiel, le scan de pointeurs
      et le scan de provinces.

``open_memory_backend()`` choisit automatiquement le backend selon la config et
la disponibilité de ``pymem``.
"""

from __future__ import annotations

import abc
import math
import random
import struct
import time

# Taille des blocs lus lors d'un scan/indexation de région (1 Mio).
SCAN_CHUNK = 0x100000


class MemoryBackend(abc.ABC):
    """Interface d'accès mémoire dont dépend le bot."""

    available: bool = False

    @abc.abstractmethod
    def attach(self) -> bool:
        """Se connecte au processus. Renvoie True en cas de succès."""

    @abc.abstractmethod
    def module_base(self) -> int:
        """Adresse de base du module principal du jeu."""

    @abc.abstractmethod
    def module_range(self) -> tuple[int, int]:
        """Plage du module principal ``(base, taille)`` — zone des pointeurs statiques."""

    @abc.abstractmethod
    def enum_regions(self) -> list[tuple[int, int]]:
        """Énumère les régions mémoire lisibles ``(adresse_base, taille)``."""

    @abc.abstractmethod
    def read_bytes(self, address: int, size: int) -> bytes:
        """Lit ``size`` octets bruts à ``address`` (b"" si illisible)."""

    # ------------------------------------------------------------------ #
    # Scan complet par régions (implémentation partagée)
    # ------------------------------------------------------------------ #
    def scan_value(self, raw: bytes) -> list[int]:
        """Renvoie TOUTES les adresses où la séquence ``raw`` apparaît."""
        n = len(raw)
        if n == 0:
            return []
        results: list[int] = []
        for base, size in self.enum_regions():
            offset = 0
            prev_tail = b""
            tail_len = n - 1
            while offset < size:
                to_read = min(SCAN_CHUNK, size - offset)
                data = self.read_bytes(base + offset, to_read)
                if not data:
                    offset += to_read
                    prev_tail = b""
                    continue
                buf = prev_tail + data
                buf_start_addr = base + offset - len(prev_tail)
                start = 0
                while True:
                    i = buf.find(raw, start)
                    if i == -1:
                        break
                    results.append(buf_start_addr + i)
                    start = i + 1
                prev_tail = buf[-tail_len:] if tail_len > 0 else b""
                offset += to_read
        return results

    # ------------------------------------------------------------------ #
    # Pointeurs (chaînes persistantes)
    # ------------------------------------------------------------------ #
    def read_pointer(self, address: int) -> int:
        """Lit un pointeur 64 bits little-endian à ``address`` (0 si illisible)."""
        data = self.read_bytes(address, 8)
        if len(data) != 8:
            return 0
        return int.from_bytes(data, "little")

    def build_pointer_index(self, alignment: int = 8) -> dict[int, list[int]]:
        """Indexe ``valeur_pointée -> [adresses qui la contiennent]``.

        Ne conserve que les pointeurs dont la valeur tombe dans une des régions
        connues (élimine le bruit). Lit chaque région par gros blocs pour rester
        efficace même sur un processus réel volumineux.
        """
        regions = self.enum_regions()
        ranges = [(b, b + s) for b, s in regions]

        def in_any(v: int) -> bool:
            for lo, hi in ranges:
                if lo <= v < hi:
                    return True
            return False

        index: dict[int, list[int]] = {}
        for base, size in regions:
            offset = 0
            while offset < size:
                to_read = min(SCAN_CHUNK, size - offset)
                data = self.read_bytes(base + offset, to_read)
                if not data:
                    offset += to_read
                    continue
                limit = len(data) - 8 + 1
                start_align = (-(base + offset)) % alignment
                i = start_align
                while i < limit:
                    v = int.from_bytes(data[i : i + 8], "little")
                    if v and in_any(v):
                        index.setdefault(v, []).append(base + offset + i)
                    i += alignment
                offset += to_read
        return index

    def resolve_chain(self, module_base: int, chain) -> int:
        """Résout une ``PointerChain`` vers l'adresse finale de la valeur.

        ptr = [module_base + static_offset] ; pour off in offsets[:-1] :
        ptr = [ptr + off] ; adresse = ptr + offsets[-1].
        """
        ptr = self.read_pointer(module_base + chain.static_offset)
        for off in chain.offsets[:-1]:
            ptr = self.read_pointer(ptr + off)
            if ptr == 0:
                return 0
        return ptr + (chain.offsets[-1] if chain.offsets else 0)

    # --- Lecture typée (basée sur read_bytes) --- #
    def read_i32(self, address: int) -> int:
        return struct.unpack("<i", self.read_bytes(address, 4))[0]

    def read_i64(self, address: int) -> int:
        return struct.unpack("<q", self.read_bytes(address, 8))[0]

    def read_f32(self, address: int) -> float:
        return struct.unpack("<f", self.read_bytes(address, 4))[0]

    def read_f64(self, address: int) -> float:
        return struct.unpack("<d", self.read_bytes(address, 8))[0]

    def read_typed(self, address: int, value_type: str) -> float | int:
        return {
            "i32": self.read_i32,
            "i64": self.read_i64,
            "f32": self.read_f32,
            "f64": self.read_f64,
        }[value_type](address)

    def close(self) -> None:  # pragma: no cover - rien à fermer par défaut
        pass


class MockMemoryBackend(MemoryBackend):
    """Processus EU5 simulé : module + tas + pointeurs + provinces + leurres."""

    available = True
    _BASE = 0x140000000        # base du module (absolue, style x64)
    _MODULE_SIZE = 0x1000      # taille de la zone "statique" (module)
    _BUF = 0x40000             # taille du tampon mémoire factice
    # Offsets, dans le module, des pointeurs statiques.
    _PTR_ECO = 0x40            # -> base de la struct économique
    _PTR_PROV = 0x60           # -> base du tableau de provinces
    _COUNT_PROV = 0x68         # i32 : nombre de provinces
    # Offsets, dans le tas, des sous-zones.
    _ECO_OFF = 0x100
    _DECOY_OFF = 0x800
    _PROV_OFF = 0x2000
    _PROV_STRIDE = 0x80
    _PROV_COUNT = 4

    # Disposition d'une struct province (offset relatif, type).
    _PROV_FIELDS = {
        "developpement": (0x00, "i32"),
        "slots_disponibles": (0x04, "i32"),
        "nb_batiments": (0x08, "i32"),
        "base_tax": (0x0C, "f32"),
    }
    # Valeurs par province (servent de calibration au scan de provinces).
    _PROV_VALUES = {
        "developpement": [24, 18, 15, 9],
        "slots_disponibles": [2, 3, 4, 1],
        "nb_batiments": [2, 1, 0, 0],
        "base_tax": [12.0, 10.0, 8.0, 5.0],
    }

    def __init__(self, seed: int = 1337) -> None:
        self._rng = random.Random(seed)
        self._mem = bytearray(self._BUF)
        self._heap_off = 0x10000  # déplacé par relaunch() pour simuler l'ASLR
        self._t0 = time.time()
        self._last_write = 0.0
        # Offsets des champs économiques dans la struct (relatifs à eco_base).
        self._eco_fields = {
            "tresor": (0x00, "f64"),
            "revenu_taxes": (0x40, "f32"),
            "revenu_production": (0x44, "f32"),
            "revenu_commerce": (0x48, "f32"),
            "revenu_sujets": (0x4C, "f32"),
            "depenses_mensuelles": (0x50, "f32"),
            "dettes": (0x54, "f32"),
            "inflation": (0x58, "f32"),
            "stabilite": (0x60, "i32"),
            "manpower": (0x64, "i32"),
            "score_puissance": (0x68, "i32"),
            "menace_militaire": (0x6C, "i32"),
        }
        self._layout()

    # -- adresses dérivées -- #
    def _heap_base(self) -> int:
        return self._BASE + self._heap_off

    def _eco_base(self) -> int:
        return self._heap_base() + self._ECO_OFF

    def _prov_base(self) -> int:
        return self._heap_base() + self._PROV_OFF

    # -- mise en place -- #
    def _layout(self) -> None:
        self._write_state(force=True)
        self._write_provinces()
        self._place_decoys()
        self._write_pointers()

    def _write_pointers(self) -> None:
        """(Ré)écrit les pointeurs statiques du module vers le tas courant."""
        self._write_typed(self._BASE + self._PTR_ECO, "i64", self._eco_base())
        self._write_typed(self._BASE + self._PTR_PROV, "i64", self._prov_base())
        self._write_typed(self._BASE + self._COUNT_PROV, "i32", self._PROV_COUNT)

    def _write_provinces(self) -> None:
        base = self._prov_base()
        for i in range(self._PROV_COUNT):
            for fld, (off, vtype) in self._PROV_FIELDS.items():
                self._write_typed(base + i * self._PROV_STRIDE + off, vtype,
                                  self._PROV_VALUES[fld][i])

    def _place_decoys(self) -> None:
        """Leurres figés égaux à la valeur initiale de tresor / manpower."""
        decoy = self._heap_base() + self._DECOY_OFF
        for fld in ("tresor", "manpower"):
            off, vtype = self._eco_fields[fld]
            value = self.read_typed(self._eco_base() + off, vtype)
            for _ in range(2):
                self._write_typed(decoy, vtype, value)
                decoy += 0x40

    def _write_typed(self, address: int, value_type: str, value) -> None:
        idx = address - self._BASE
        packed = {
            "i32": lambda v: struct.pack("<i", int(v)),
            "i64": lambda v: struct.pack("<q", int(v)),
            "f32": lambda v: struct.pack("<f", float(v)),
            "f64": lambda v: struct.pack("<d", float(v)),
        }[value_type](value)
        self._mem[idx : idx + len(packed)] = packed

    def _write_state(self, force: bool = False) -> None:
        """État économique variant lentement (throttlé à 0.25 s pour des scans
        cohérents)."""
        now = time.time()
        if not force and (now - self._last_write) < 0.25:
            return
        self._last_write = now
        t = now - self._t0
        wave = math.sin(t / 30.0)
        taxes = 18 + 4 * wave + self._rng.uniform(-0.5, 0.5)
        prod = 12 + 3 * math.cos(t / 25.0)
        commerce = 9 + 2 * wave
        sujets = 3.0
        depenses = 30 + 5 * math.sin(t / 18.0)
        revenu = taxes + prod + commerce + sujets
        tresor = 500 + (revenu - depenses) * (t / 5.0)
        values = {
            "tresor": max(0.0, tresor),
            "revenu_taxes": taxes,
            "revenu_production": prod,
            "revenu_commerce": commerce,
            "revenu_sujets": sujets,
            "depenses_mensuelles": depenses,
            "dettes": max(0.0, 200 - t),
            "inflation": 1.5 + 1.5 * (math.sin(t / 40.0) + 1) / 2,
            "stabilite": int(round(1 + wave)),
            "manpower": 15000 + int(2000 * math.cos(t / 22.0)),
            "score_puissance": 55 + int(10 * wave),
            "menace_militaire": max(0, int(30 + 25 * math.sin(t / 35.0))),
        }
        eco = self._eco_base()
        for fld, val in values.items():
            off, vtype = self._eco_fields[fld]
            self._write_typed(eco + off, vtype, val)

    def advance(self, seconds: float) -> None:
        """Avance le temps simulé (scan différentiel scalaire hors-ligne)."""
        self._t0 -= seconds
        self._write_state(force=True)

    def relaunch(self, new_heap_off: int | None = None) -> None:
        """Simule une relance du jeu : déplace le tas (ASLR) et recâble les
        pointeurs statiques. Les adresses absolues changent, mais les chaînes de
        pointeurs restent valides."""
        old = self._heap_off
        if new_heap_off is None:
            new_heap_off = 0x18000 if old == 0x10000 else 0x10000
        span = self._PROV_OFF + self._PROV_COUNT * self._PROV_STRIDE + 0x100
        block = bytes(self._mem[old : old + span])
        # efface l'ancien emplacement, recopie au nouveau
        self._mem[old : old + span] = b"\x00" * span
        self._heap_off = new_heap_off
        self._mem[new_heap_off : new_heap_off + span] = block
        self._write_pointers()

    # -- calibration provinces (sert d'oracle au scan de provinces) -- #
    def province_calibration(self) -> tuple[dict[str, list], dict[str, str]]:
        values = {k: list(v) for k, v in self._PROV_VALUES.items()}
        types = {k: t for k, (_, t) in self._PROV_FIELDS.items()}
        return values, types

    # -- interface MemoryBackend -- #
    def attach(self) -> bool:
        return True

    def module_base(self) -> int:
        return self._BASE

    def module_range(self) -> tuple[int, int]:
        return (self._BASE, self._MODULE_SIZE)

    def enum_regions(self) -> list[tuple[int, int]]:
        return [(self._BASE, len(self._mem))]

    def address_of(self, field: str) -> int:
        if field in self._eco_fields:
            return self._eco_base() + self._eco_fields[field][0]
        return 0

    def type_of(self, field: str) -> str:
        return self._eco_fields.get(field, (0, "i32"))[1]

    def fields(self) -> list[str]:
        return list(self._eco_fields)

    def read_bytes(self, address: int, size: int) -> bytes:
        self._write_state()  # rafraîchit l'état (throttlé) avant lecture
        idx = address - self._BASE
        if idx < 0 or idx + size > len(self._mem):
            return b"\x00" * size
        return bytes(self._mem[idx : idx + size])


def open_memory_backend(config) -> MemoryBackend:
    """Sélectionne et ouvre le backend mémoire selon la configuration."""
    mode = config.memory_backend
    if mode == "mock":
        backend: MemoryBackend = MockMemoryBackend()
        backend.attach()
        return backend

    if mode in ("auto", "pymem"):
        try:
            from .pymem_backend import PymemBackend

            backend = PymemBackend(config.process_name)
            if backend.attach():
                return backend
            if mode == "pymem":
                raise RuntimeError(
                    f"Processus '{config.process_name}' introuvable pour le backend pymem."
                )
        except ImportError:
            if mode == "pymem":
                raise RuntimeError("pymem n'est pas installé (requis pour le backend 'pymem').")

    backend = MockMemoryBackend()
    backend.attach()
    return backend
