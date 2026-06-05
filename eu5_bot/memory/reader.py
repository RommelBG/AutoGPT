"""Lecture continue de l'état du jeu (PHASE 2 — étape de lecture).

``GameStateReader`` utilise une ``MemoryMap`` et un ``MemoryBackend`` pour
produire un ``GameState`` à jour à chaque cycle de décision.
"""

from __future__ import annotations

from ..models import GameState, MemoryMap, Province
from .backend import MemoryBackend, MockMemoryBackend


class GameStateReader:
    """Reconstitue un ``GameState`` à partir des adresses cartographiées."""

    def __init__(self, backend: MemoryBackend, memory_map: MemoryMap) -> None:
        self.backend = backend
        self.memory_map = memory_map

    def _read_field(self, field: str, default: float | int = 0):
        sig = self.memory_map.signatures.get(field)
        if sig is None or not sig.address:
            return default
        try:
            return self.backend.read_typed(sig.address, sig.value_type)
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
        # Intérêts mensuels approximés (5 % annuel des dettes).
        state.interets_mensuels = round(state.dettes * 0.05 / 12.0, 2)
        state.provinces = self._read_provinces()
        return state

    def _read_provinces(self) -> list[Province]:
        """Provinces : non cartographiées en PHASE 1 (économie d'abord).

        Le backend mock fournit un échantillon réaliste pour alimenter le
        conseiller Constructeur ; le backend réel renverra une liste vide tant
        que le scan des provinces n'est pas implémenté.
        """
        if isinstance(self.backend, MockMemoryBackend):
            return [
                Province("Capitale", 24, "terre", "catholique", "francien",
                         ["temple", "atelier"], 2),
                Province("Port-Marchand", 18, "côte", "catholique", "normand",
                         ["marché"], 3),
                Province("Vallée-Fertile", 15, "terre", "catholique", "occitan",
                         [], 4),
            ]
        return []
