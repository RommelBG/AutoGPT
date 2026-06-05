"""Abstraction de l'accès mémoire du processus EU5.

Le reste du bot ne dépend que de l'interface ``MemoryBackend``. Deux
implémentations sont fournies :

    - ``PymemBackend``     : lecture réelle via ``pymem`` (Windows + jeu lancé),
      avec énumération des régions mémoire et scan complet de toutes les valeurs.
    - ``MockMemoryBackend``: simulation d'une partie qui évolue dans le temps,
      avec des *leurres* (adresses figées partageant la valeur initiale d'un
      champ) afin que le scan différentiel soit réellement exercé et testable
      hors-ligne, sans le jeu ni Windows.

``open_memory_backend()`` choisit automatiquement le bon backend selon la
configuration et la disponibilité de ``pymem``.
"""

from __future__ import annotations

import abc
import math
import random
import struct
import time

# Taille des blocs lus lors d'un scan de région (1 Mio).
SCAN_CHUNK = 0x100000


class MemoryBackend(abc.ABC):
    """Interface minimale d'accès mémoire dont dépend le bot."""

    available: bool = False

    @abc.abstractmethod
    def attach(self) -> bool:
        """Se connecte au processus. Renvoie True en cas de succès."""

    @abc.abstractmethod
    def module_base(self) -> int:
        """Adresse de base du module principal du jeu."""

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
        """Renvoie TOUTES les adresses où la séquence ``raw`` apparaît.

        Parcourt chaque région par blocs avec recouvrement (``len(raw) - 1``)
        afin de capturer les occurrences à cheval sur deux blocs.
        """
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
                # L'octet 0 de ``buf`` correspond à l'adresse :
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
    """Simule un processus EU5 : une partie économique qui évolue.

    Le backend maintient les champs économiques à des adresses dédiées et y
    écrit des valeurs variant lentement dans le temps. Il place en outre des
    *leurres* : des adresses figées contenant la valeur initiale de certains
    champs, de sorte qu'un scan de valeur unique reste ambigu et que seul le
    scan différentiel parvient à isoler la bonne adresse — comme face au jeu.
    """

    available = True
    _BASE = 0x140000000  # base de module factice plausible (style x64)

    def __init__(self, seed: int = 1337) -> None:
        self._rng = random.Random(seed)
        self._mem = bytearray(0x4000)  # tampon mémoire factice
        self._addr_of: dict[str, int] = {}
        self._type_of: dict[str, str] = {}
        self._t0 = time.time()
        self._last_write = 0.0
        self._layout()

    # -- mise en place du "processus" simulé -- #
    def _layout(self) -> None:
        plan = [
            ("tresor", "f64"),
            ("revenu_taxes", "f32"),
            ("revenu_production", "f32"),
            ("revenu_commerce", "f32"),
            ("revenu_sujets", "f32"),
            ("depenses_mensuelles", "f32"),
            ("dettes", "f32"),
            ("inflation", "f32"),
            ("stabilite", "i32"),
            ("manpower", "i32"),
            ("score_puissance", "i32"),
            ("menace_militaire", "i32"),
        ]
        offset = 0x100
        for fld, vtype in plan:
            self._addr_of[fld] = self._BASE + offset
            self._type_of[fld] = vtype
            offset += 0x40  # espacement entre champs
        self._write_state(force=True)
        self._place_decoys()

    def _place_decoys(self) -> None:
        """Écrit des leurres figés égaux à la valeur initiale de certains champs.

        Ces adresses ne sont JAMAIS mises à jour par ``_write_state`` : elles
        rendent le premier scan ambigu (plusieurs candidats) tout en se laissant
        éliminer par le scan différentiel dès que le vrai champ change.
        """
        decoy_offset = 0x800
        for fld in ("tresor", "manpower"):
            vtype = self._type_of[fld]
            value = self.read_typed(self._addr_of[fld], vtype)
            for _ in range(2):  # deux leurres par champ
                self._write_typed(self._BASE + decoy_offset, vtype, value)
                decoy_offset += 0x40

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
        """Calcule un état plausible variant lentement dans le temps.

        Le calcul est *throttlé* (au plus une fois par 0.25 s) afin que toutes
        les lectures effectuées pendant un même scan (qui dure quelques ms)
        portent sur un instantané cohérent ; entre deux cycles de jeu (ou après
        ``advance``), l'état est rafraîchi et varie comme attendu.
        """
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
        # Trésor : accumule le revenu net au fil du temps
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
        for fld, val in values.items():
            self._write_typed(self._addr_of[fld], self._type_of[fld], val)

    def advance(self, seconds: float) -> None:
        """Avance le temps simulé (utilisé par le scan différentiel hors-ligne).

        Décale l'origine temporelle puis force un recalcul : les champs évoluent,
        les leurres restent figés.
        """
        self._t0 -= seconds
        self._write_state(force=True)

    # -- interface MemoryBackend -- #
    def attach(self) -> bool:
        return True

    def module_base(self) -> int:
        return self._BASE

    def enum_regions(self) -> list[tuple[int, int]]:
        return [(self._BASE, len(self._mem))]

    def address_of(self, field: str) -> int:
        """Adresse simulée d'un champ (utilisée par les tests / la calibration)."""
        return self._addr_of.get(field, 0)

    def type_of(self, field: str) -> str:
        return self._type_of.get(field, "i32")

    def fields(self) -> list[str]:
        return list(self._addr_of)

    def read_bytes(self, address: int, size: int) -> bytes:
        self._write_state()  # rafraîchit l'état (throttlé) avant lecture
        idx = address - self._BASE
        if idx < 0 or idx + size > len(self._mem):
            return b"\x00" * size
        return bytes(self._mem[idx : idx + size])


def open_memory_backend(config) -> MemoryBackend:
    """Sélectionne et ouvre le backend mémoire selon la configuration.

    "auto"  : pymem si importable et processus présent, sinon mock.
    "pymem" : force pymem (lève si indisponible).
    "mock"  : force la simulation.
    """
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

    # Repli : simulation
    backend = MockMemoryBackend()
    backend.attach()
    return backend
