"""Configuration centrale du bot EU5.

Charge les valeurs depuis l'environnement (et un éventuel fichier ``.env``) et
expose un objet ``Config`` immuable consommé par tous les autres modules. Aucun
secret n'est codé en dur : en l'absence de clé API, le conseiller concerné
bascule en mode "mock".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # chargement optionnel du fichier .env
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - python-dotenv absent
    pass


# Répertoire où sont stockées la carte mémoire et les journaux.
DATA_DIR = Path(os.environ.get("EU5_DATA_DIR", Path.home() / ".eu5_bot"))
MEMORY_MAP_PATH = DATA_DIR / "memory_map.json"


@dataclass
class AdvisorConfig:
    """Configuration d'un conseiller : son fournisseur LLM et son modèle.

    Volontairement *mutable* : seul ``enabled`` change à l'exécution (toggle de
    l'interface). ``Config`` reste immuable et conserve une référence vers cet
    objet, donc muter ``enabled`` en place suffit.
    """

    name: str
    provider: str  # "cerebras" | "deepseek" | "groq" | "anthropic"
    model: str
    enabled: bool = True


@dataclass(frozen=True)
class Config:
    """Configuration complète et immuable du bot."""

    # Clés API (vides => mode mock pour le fournisseur concerné)
    cerebras_api_key: str = ""
    deepseek_api_key: str = ""
    groq_api_key: str = ""
    anthropic_api_key: str = ""

    # Conseillers (les 4 + le coordinateur)
    tresorier: AdvisorConfig = field(
        default_factory=lambda: AdvisorConfig("Trésorier", "cerebras", "qwen-3-32b")
    )
    constructeur: AdvisorConfig = field(
        default_factory=lambda: AdvisorConfig("Constructeur", "deepseek", "deepseek-reasoner")
    )
    stratege: AdvisorConfig = field(
        default_factory=lambda: AdvisorConfig("Stratège", "deepseek", "deepseek-reasoner")
    )
    contradicteur: AdvisorConfig = field(
        default_factory=lambda: AdvisorConfig("Contradicteur", "cerebras", "qwen-3-32b")
    )
    coordinateur: AdvisorConfig = field(
        default_factory=lambda: AdvisorConfig("Coordinateur", "anthropic", "claude-sonnet-4-6")
    )

    # Backends
    memory_backend: str = "auto"  # auto | pymem | mock
    action_backend: str = "auto"  # auto | pyautogui | mock
    process_name: str = "eu5.exe"

    # Comportement
    objectif: str = "Devenir la première puissance économique d'Europe d'ici 1600"
    tick_seconds: float = 10.0

    @property
    def advisors(self) -> list[AdvisorConfig]:
        """Les quatre conseillers (hors coordinateur), dans l'ordre du Conseil."""
        return [self.tresorier, self.constructeur, self.stratege, self.contradicteur]

    def api_key_for(self, provider: str) -> str:
        """Renvoie la clé API associée à un fournisseur (chaîne vide si absente)."""
        return {
            "cerebras": self.cerebras_api_key,
            "deepseek": self.deepseek_api_key,
            "groq": self.groq_api_key,
            "anthropic": self.anthropic_api_key,
        }.get(provider, "")


def _advisor(name: str, env_model: str, provider: str, default_model: str) -> AdvisorConfig:
    return AdvisorConfig(name, provider, os.environ.get(env_model, default_model))


def load_config() -> Config:
    """Construit la configuration à partir des variables d'environnement."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Config(
        cerebras_api_key=os.environ.get("CEREBRAS_API_KEY", ""),
        deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        groq_api_key=os.environ.get("GROQ_API_KEY", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        tresorier=_advisor("Trésorier", "EU5_MODEL_TRESORIER", "cerebras", "qwen-3-32b"),
        constructeur=_advisor(
            "Constructeur", "EU5_MODEL_CONSTRUCTEUR", "deepseek", "deepseek-reasoner"
        ),
        stratege=_advisor("Stratège", "EU5_MODEL_STRATEGE", "deepseek", "deepseek-reasoner"),
        contradicteur=_advisor(
            "Contradicteur", "EU5_MODEL_CONTRADICTEUR", "cerebras", "qwen-3-32b"
        ),
        coordinateur=_advisor(
            "Coordinateur", "EU5_MODEL_COORDINATEUR", "anthropic", "claude-sonnet-4-6"
        ),
        memory_backend=os.environ.get("EU5_MEMORY_BACKEND", "auto"),
        action_backend=os.environ.get("EU5_ACTION_BACKEND", "auto"),
        process_name=os.environ.get("EU5_PROCESS_NAME", "eu5.exe"),
        objectif=os.environ.get(
            "EU5_OBJECTIF", "Devenir la première puissance économique d'Europe d'ici 1600"
        ),
        tick_seconds=float(os.environ.get("EU5_TICK_SECONDS", "10")),
    )
