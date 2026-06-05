"""Lecture continue de l'état du jeu (PHASE 2 — étape de lecture).

``GameStateReader`` reconstitue un ``GameState`` à chaque cycle à partir de la
``MemoryMap``. Pour chaque champ scalaire, si une **chaîne de pointeurs
persistante** est connue, elle est résolue à la volée (l'adresse reste valide
après une relance du jeu) ; sinon on retombe sur l'adresse absolue (valable pour
la session courante). Les provinces sont lues via le ``ProvinceLayout`` quand il
est disponible.
"""

from __future__ import annotations

from ..models import GameState, MemoryMap, Province
from .backend import MemoryBackend, MockMemoryBackend
from .provinces import read_provinces


class GameStateReader:
    """Reconstitue un ``GameState`` à partir des adresses cartographiées."""

    def __init__(self, backend: MemoryBackend, memory_map: MemoryMap) -> None:
        self.backend = backend
        self.memory_map = memory_map

    def _resolve_address(self, sig) -> int:
        """Adresse effective d'un champ : via chaîne de pointeurs si possible."""
        if sig.pointer_chain is not None:
            addr = self.backend.resolve_chain(self.memory_map.module_base, sig.pointer_chain)
            if addr:
                return addr
        return sig.address

    def _read_field(self, field: str, default: float | int = 0):
        sig = self.memory_map.signatures.get(field)
        if sig is None:
            return default
        addr = self._resolve_address(sig)
        if not addr:
            return default
        try:
            return self.backend.read_typed(addr, sig.value_type)
        except Exception:
            return default

    def read(self) -> GameState:
        """Lit l'état économique courant."""
        taxes = float(self._read_field("revenu_taxes"))
        production = float(self._read_field("revenu_production"))
        commerce = float(self._read_field("revenu_commerce"))
        sujets = float(self._read_field("revenu_sujets"))
        depenses = float(self._read_field("depenses_mensuelles"))

        state = GameState(
            tresor=float(self._read_field("tresor")),
            revenu_taxes=taxes,
            revenu_production=production,
            revenu_commerce=commerce,
            revenu_sujets=sujets,
            revenu_mensuel=taxes + production + commerce + sujets,
            depenses_mensuelles=depenses,
            dettes=float(self._read_field("dettes")),
            inflation=float(self._read_field("inflation")),
            stabilite=int(self._read_field("stabilite")),
            manpower=int(self._read_field("manpower")),
            score_puissance=int(self._read_field("score_puissance", 50)),
            menace_militaire=int(self._read_field("menace_militaire")),
        )
        state.interets_mensuels = round(state.dettes * 0.05 / 12.0, 2)
        state.provinces = self._read_provinces()
        return state

    def _read_provinces(self) -> list[Province]:
        """Lit les provinces via le ``ProvinceLayout`` cartographié.

        Si aucun layout n'est disponible (jeu réel non calibré), renvoie une
        liste vide ; sur mock sans layout, un échantillon est fourni en repli.
        """
        layout = self.memory_map.province_layout
        if layout is not None:
            return read_provinces(self.backend, layout, self.memory_map.module_base)
        if isinstance(self.backend, MockMemoryBackend):
            return [
                Province("Capitale", 24, "terre", "catholique", "francien",
                         ["temple", "atelier"], 2),
            ]
        return []
