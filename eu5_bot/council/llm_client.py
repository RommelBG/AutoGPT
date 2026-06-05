"""Client LLM multi-fournisseurs pour le Conseil.

Trois familles d'appels :
    - Endpoints OpenAI-compatibles (Cerebras / DeepSeek / Groq) via ``httpx``.
    - Coordinateur Claude Sonnet 4.6 via le SDK officiel ``anthropic`` (async).
    - Repli "mock" : si aucune clé n'est disponible (ou en cas d'erreur réseau),
      une réponse JSON plausible est générée hors-ligne pour chaque conseiller,
      ce qui permet de faire tourner et tester tout le pipeline sans clés.

Tous les appels sont asynchrones afin que les 4 conseillers s'exécutent en
parallèle (cf. ``council.Council``).
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..config import Config

# Endpoints OpenAI-compatibles par fournisseur.
OPENAI_ENDPOINTS = {
    "cerebras": "https://api.cerebras.ai/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
}

# Repli de vitesse : si Cerebras est indisponible, basculer sur Groq.
PROVIDER_FALLBACK = {"cerebras": "groq"}


def extract_json(text: str) -> dict[str, Any]:
    """Extrait le premier objet JSON d'une réponse LLM, tolérant au bruit.

    Gère les blocs ```json ... ``` et les balises de raisonnement DeepSeek-R1
    (``<think>...</think>``) en isolant le premier ``{ ... }`` équilibré.
    """
    if not text:
        raise ValueError("réponse vide")
    # Retire un éventuel bloc de raisonnement.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Retire les clôtures markdown.
    text = text.replace("```json", "```")
    fence = text.split("```")
    if len(fence) >= 3:
        text = fence[1]
    # Cherche le premier objet JSON équilibré.
    start = text.find("{")
    if start == -1:
        raise ValueError("aucun objet JSON trouvé")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("objet JSON non terminé")


class LLMClient:
    """Effectue les appels LLM pour un conseiller donné, avec repli mock."""

    def __init__(self, config: Config, timeout: float = 60.0) -> None:
        self.config = config
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    # Routage
    # ------------------------------------------------------------------ #
    def _resolve_provider(self, provider: str) -> tuple[str, str]:
        """Renvoie (fournisseur effectif, clé) en appliquant le repli.

        Renvoie une clé vide si aucun fournisseur utilisable -> mode mock.
        """
        key = self.config.api_key_for(provider)
        if key:
            return provider, key
        fallback = PROVIDER_FALLBACK.get(provider)
        if fallback:
            fk = self.config.api_key_for(fallback)
            if fk:
                return fallback, fk
        return provider, ""

    async def complete_json(
        self, advisor_name: str, provider: str, model: str, system: str, user: str
    ) -> tuple[dict[str, Any], str, str]:
        """Appelle le LLM et renvoie ``(json, texte_brut, source)``.

        ``source`` ∈ {"llm", "mock"}. Lève en cas d'échec réseau réel (le Conseil
        gère l'exception et bascule en mock).
        """
        eff_provider, key = self._resolve_provider(provider)
        if not key:
            data = mock_response(advisor_name)
            return data, json.dumps(data, ensure_ascii=False), "mock"

        if eff_provider == "anthropic":
            text = await self._call_anthropic(model, system, user, key)
        else:
            text = await self._call_openai_compatible(eff_provider, model, system, user, key)
        return extract_json(text), text, "llm"

    # ------------------------------------------------------------------ #
    # Implémentations par fournisseur
    # ------------------------------------------------------------------ #
    async def _call_openai_compatible(
        self, provider: str, model: str, system: str, user: str, key: str
    ) -> str:
        url = OPENAI_ENDPOINTS[provider]
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        return body["choices"][0]["message"]["content"]

    async def _call_anthropic(self, model: str, system: str, user: str, key: str) -> str:
        # Import local : le SDK n'est requis que pour le coordinateur.
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=key)
        message = await client.messages.create(
            model=model,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in message.content if b.type == "text")


# --------------------------------------------------------------------------- #
# Réponses simulées (mode hors-ligne / repli)
# --------------------------------------------------------------------------- #
def mock_response(advisor_name: str) -> dict[str, Any]:
    """Réponse JSON plausible, conforme au format de chaque conseiller."""
    return {
        "Trésorier": {
            "statut_financier": "SAIN",
            "budget_disponible_construction": 200,
            "recommandation": "Investir dans un bâtiment générateur de revenu",
            "alerte": None,
            "confiance": 75,
        },
        "Constructeur": {
            "province_cible": "Capitale",
            "batiment_recommande": "marché",
            "cout": 150,
            "benefice_attendu": "+15% revenu commercial provincial",
            "priorite": "HAUTE",
            "confiance": 80,
        },
        "Stratège": {
            "alignement_objectif": "OPTIMAL",
            "priorite_strategique": "Renforcer l'économie avant expansion",
            "horizon": "moyen",
            "veto": False,
            "raison_veto": None,
            "confiance": 70,
        },
        "Contradicteur": {
            "risques_identifies": ["Menace militaire d'un voisin", "Event négatif possible"],
            "conseil_conteste": "Aucun",
            "argument": "Le trésor reste suffisant pour absorber un choc modéré",
            "contre_proposition": None,
            "niveau_alerte": "VERT",
            "confiance": 65,
        },
        "Coordinateur": {
            "decision_finale": "Construire un marché dans la Capitale",
            "province": "Capitale",
            "action": "marché",
            "consensus": 78,
            "bloque": False,
            "raison_blocage": None,
            "prochaine_evaluation": "dans 3 tours",
        },
    }[advisor_name]
