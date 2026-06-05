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
class PointerChain:
    """Chaîne de pointeurs *persistante* menant à une valeur.

    Résiste aux relances du jeu (ASLR / réallocation du tas) : on stocke un
    pointeur statique dans le module (``module_base + static_offset``) puis une
    suite d'offsets. Résolution (sémantique Cheat Engine) :

        ptr = lire_pointeur(module_base + static_offset)
        pour off in offsets[:-1] : ptr = lire_pointeur(ptr + off)
        adresse_valeur = ptr + offsets[-1]
    """

    static_offset: int
    offsets: list[int] = field(default_factory=list)
    module: str = ""  # nom du module porteur du pointeur statique (vide = principal)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PointerChain":
        return cls(
            static_offset=data.get("static_offset", 0),
            offsets=list(data.get("offsets", [])),
            module=data.get("module", ""),
        )


@dataclass
class MemorySignature:
    """Adresse découverte pour un champ donné, avec ses moyens de re-localisation.

    ``address``       : adresse absolue isolée (valable pour la session courante).
    ``pointer_chain`` : chaîne de pointeurs persistante (survit aux relances) ;
                        si présente, elle est résolue à chaque lecture.
    ``pattern``       : signature AOB des octets voisins (résistance aux patchs).
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
    # Chaîne de pointeurs persistante (None tant qu'aucune n'a été trouvée).
    pointer_chain: "PointerChain | None" = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemorySignature":
        pc = data.get("pointer_chain")
        return cls(
            field=data["field"],
            address=data.get("address", 0),
            offsets=list(data.get("offsets", [])),
            pattern=data.get("pattern", ""),
            value_type=data.get("value_type", "i32"),
            candidates=list(data.get("candidates", [])),
            confidence=data.get("confidence", 0.0),
            pointer_chain=PointerChain.from_dict(pc) if pc else None,
        )


@dataclass
class ProvinceLayout:
    """Disposition mémoire du tableau de provinces (structures contiguës).

    Permet de lire dynamiquement toutes les provinces : on résout ``base``
    (adresse de la 1re structure, via pointeur statique persistant si possible),
    puis on itère ``count`` fois en sautant de ``stride`` octets, en lisant
    chaque champ à son offset dans ``field_offsets``.
    """

    base_address: int = 0
    stride: int = 0
    count: int = 0
    field_offsets: dict[str, int] = field(default_factory=dict)  # nom -> (offset, type)
    field_types: dict[str, str] = field(default_factory=dict)
    pointer_chain: "PointerChain | None" = None  # vers base_address (persistant)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_address": self.base_address,
            "stride": self.stride,
            "count": self.count,
            "field_offsets": self.field_offsets,
            "field_types": self.field_types,
            "pointer_chain": self.pointer_chain.to_dict() if self.pointer_chain else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProvinceLayout":
        pc = data.get("pointer_chain")
        return cls(
            base_address=data.get("base_address", 0),
            stride=data.get("stride", 0),
            count=data.get("count", 0),
            field_offsets={k: int(v) for k, v in data.get("field_offsets", {}).items()},
            field_types=dict(data.get("field_types", {})),
            pointer_chain=PointerChain.from_dict(pc) if pc else None,
        )


@dataclass
class MemoryMap:
    """Carte des adresses mémoire découvertes pour le processus EU5."""

    process_name: str = "eu5.exe"
    module_base: int = 0
    game_version: str = "unknown"
    signatures: dict[str, MemorySignature] = field(default_factory=dict)
    province_layout: "ProvinceLayout | None" = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "process_name": self.process_name,
            "module_base": self.module_base,
            "game_version": self.game_version,
            "created_at": self.created_at,
            "signatures": {k: v.to_dict() for k, v in self.signatures.items()},
            "province_layout": self.province_layout.to_dict() if self.province_layout else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryMap":
        sigs = {
            k: MemorySignature.from_dict(v) for k, v in data.get("signatures", {}).items()
        }
        pl = data.get("province_layout")
        return cls(
            process_name=data.get("process_name", "eu5.exe"),
            module_base=data.get("module_base", 0),
            game_version=data.get("game_version", "unknown"),
            signatures=sigs,
            province_layout=ProvinceLayout.from_dict(pl) if pl else None,
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
