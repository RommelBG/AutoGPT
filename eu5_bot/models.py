"""Structures de données partagées par tout le bot.

On utilise des ``dataclass`` simples, sérialisables en JSON, pour :
    - ``Province``        : une province et ses bâtiments.
    - ``GameState``       : l'état économique complet lu en mémoire.
    - ``MemoryMap``       : la carte des adresses mémoire découvertes au scan.
    - ``AdvisorResponse`` : la réponse JSON d'un conseiller.
    - ``CouncilDecision`` : la décision finale du coordinateur.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any


# --------------------------------------------------------------------------- #
# État du jeu
# --------------------------------------------------------------------------- #
@dataclass
class Province:
    """Une province et son état de développement."""

    nom: str
    developpement: int = 0
    type: str = "terre"
    religion: str = ""
    culture: str = ""
    batiments: list[str] = field(default_factory=list)
    slots_disponibles: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GameState:
    """Photographie de l'état économique du jeu à un instant donné."""

    # Temps de jeu
    date: str = "1337.1.1"

    # Finances
    tresor: float = 0.0
    revenu_mensuel: float = 0.0
    revenu_taxes: float = 0.0
    revenu_production: float = 0.0
    revenu_commerce: float = 0.0
    revenu_sujets: float = 0.0
    depenses_mensuelles: float = 0.0
    dettes: float = 0.0
    interets_mensuels: float = 0.0

    # Indicateurs
    inflation: float = 0.0
    stabilite: int = 0
    manpower: int = 0

    # Militaire / menace (0-100)
    score_puissance: int = 50
    menace_militaire: int = 0

    # Provinces
    provinces: list[Province] = field(default_factory=list)

    # Métadonnées
    timestamp: float = field(default_factory=time.time)

    @property
    def revenu_net(self) -> float:
        return self.revenu_mensuel - self.depenses_mensuelles

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def to_prompt_json(self) -> str:
        """Sérialisation compacte transmise aux conseillers LLM."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Carte mémoire
# --------------------------------------------------------------------------- #
@dataclass
class MemorySignature:
    """Adresse découverte pour un champ donné, avec sa signature de validation.

    ``offsets`` : chaîne de pointeurs (base + offsets) menant à la valeur.
    ``pattern`` : signature AOB (array-of-bytes) servant à re-localiser l'adresse
                  après une mise à jour du jeu (résistance aux patchs).
    """

    field: str
    address: int = 0
    offsets: list[int] = field(default_factory=list)
    pattern: str = ""
    value_type: str = "i32"  # i32 | i64 | f32 | f64
    # Candidats restants après le scan différentiel (le 1er est retenu) et
    # confiance ∈ [0,1] : 1.0 si une seule adresse a survécu, sinon dégressive.
    candidates: list[int] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryMap:
    """Carte des adresses mémoire découvertes pour le processus EU5."""

    process_name: str = "eu5.exe"
    module_base: int = 0
    game_version: str = "unknown"
    signatures: dict[str, MemorySignature] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "process_name": self.process_name,
            "module_base": self.module_base,
            "game_version": self.game_version,
            "created_at": self.created_at,
            "signatures": {k: v.to_dict() for k, v in self.signatures.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryMap":
        sigs = {
            k: MemorySignature(**v) for k, v in data.get("signatures", {}).items()
        }
        return cls(
            process_name=data.get("process_name", "eu5.exe"),
            module_base=data.get("module_base", 0),
            game_version=data.get("game_version", "unknown"),
            signatures=sigs,
            created_at=data.get("created_at", time.time()),
        )

    def save(self, path) -> None:
        from pathlib import Path

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "MemoryMap | None":
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            return None
        try:
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return None


# --------------------------------------------------------------------------- #
# Conseil
# --------------------------------------------------------------------------- #
@dataclass
class AdvisorResponse:
    """Réponse d'un conseiller : le JSON brut analysé + métadonnées."""

    advisor: str
    data: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    ok: bool = True
    error: str = ""
    source: str = "llm"  # "llm" | "mock" | "error"
    latency_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CouncilDecision:
    """Décision finale du coordinateur, prête à être exécutée."""

    decision_finale: str = ""
    province: str = ""
    action: str = ""
    consensus: int = 0
    bloque: bool = False
    raison_blocage: str = ""
    prochaine_evaluation: str = ""
    # Trace : réponses des 4 conseillers ayant mené à la décision
    advisors: list[AdvisorResponse] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_finale": self.decision_finale,
            "province": self.province,
            "action": self.action,
            "consensus": self.consensus,
            "bloque": self.bloque,
            "raison_blocage": self.raison_blocage,
            "prochaine_evaluation": self.prochaine_evaluation,
            "advisors": [a.to_dict() for a in self.advisors],
            "timestamp": self.timestamp,
        }
