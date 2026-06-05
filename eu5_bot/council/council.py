"""Orchestrateur du Conseil LLM (PHASE 2 — analyse & décision).

Déroulé d'un cycle :
    1. Les 4 conseillers reçoivent le même état du jeu et répondent EN PARALLÈLE.
    2. Le coordinateur reçoit les 4 JSON et rend la décision finale.
    3. La décision (avec la trace des conseillers) est renvoyée au bot.

Le Conseil est résilient : toute erreur d'un conseiller (réseau, JSON invalide)
est capturée et remplacée par une réponse mock, de sorte qu'un cycle aboutit
toujours à une décision.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Callable

from ..config import AdvisorConfig, Config
from ..models import AdvisorResponse, CouncilDecision, GameState
from . import coordinator, prompts
from .llm_client import LLMClient, mock_response

# Callback optionnel de progression : (nom_conseiller, réponse).
AdvisorCallback = Callable[[AdvisorResponse], None]


class Council:
    """Le Conseil : 4 conseillers en parallèle + coordinateur final."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = LLMClient(config)

    async def deliberate(
        self,
        state: GameState,
        on_advisor: AdvisorCallback | None = None,
    ) -> CouncilDecision:
        """Exécute un cycle complet de délibération et renvoie la décision."""
        # 1. Les 4 conseillers en parallèle.
        enabled = [a for a in self.config.advisors if a.enabled]
        user_payload = self._advisor_user_payload(state)
        tasks = [self._run_advisor(a, user_payload, on_advisor) for a in enabled]
        advisors: list[AdvisorResponse] = await asyncio.gather(*tasks)

        # 2. Coordinateur final.
        decision = await self._coordinate(state, advisors)
        return decision

    # ------------------------------------------------------------------ #
    # Conseillers
    # ------------------------------------------------------------------ #
    def _advisor_user_payload(self, state: GameState) -> str:
        return (
            f"Objectif global : {self.config.objectif}\n\n"
            f"État actuel du jeu (JSON) :\n{state.to_prompt_json()}\n\n"
            "Réponds uniquement par le JSON strict de ton format."
        )

    async def _run_advisor(
        self,
        advisor: AdvisorConfig,
        user_payload: str,
        on_advisor: AdvisorCallback | None,
    ) -> AdvisorResponse:
        system = prompts.ADVISOR_PROMPTS[advisor.name]
        t0 = time.time()
        try:
            data, raw, source = await self.client.complete_json(
                advisor.name, advisor.provider, advisor.model, system, user_payload
            )
            resp = AdvisorResponse(
                advisor=advisor.name, data=data, raw=raw, ok=True,
                source=source, latency_s=round(time.time() - t0, 2),
            )
        except Exception as exc:  # repli mock en cas d'échec
            data = mock_response(advisor.name)
            resp = AdvisorResponse(
                advisor=advisor.name, data=data,
                raw=json.dumps(data, ensure_ascii=False),
                ok=True, error=str(exc), source="mock",
                latency_s=round(time.time() - t0, 2),
            )
        if on_advisor:
            on_advisor(resp)
        return resp

    # ------------------------------------------------------------------ #
    # Coordinateur
    # ------------------------------------------------------------------ #
    async def _coordinate(
        self, state: GameState, advisors: list[AdvisorResponse]
    ) -> CouncilDecision:
        coord = self.config.coordinateur
        key = self.config.api_key_for(coord.provider)
        if not key:
            # Pas de clé coordinateur : moteur de règles déterministe.
            return coordinator.apply_rules(advisors)

        system = prompts.COORDINATEUR
        user = (
            f"Objectif global : {self.config.objectif}\n\n"
            f"État du jeu (JSON) :\n{state.to_prompt_json()}\n\n"
            "Analyses des 4 conseillers (JSON) :\n"
            + json.dumps({a.advisor: a.data for a in advisors}, ensure_ascii=False, indent=2)
            + "\n\nRends la décision finale au format JSON strict."
        )
        try:
            data, _, _ = await self.client.complete_json(
                coord.name, coord.provider, coord.model, system, user
            )
            return coordinator.merge_llm_decision(data, advisors)
        except Exception:
            # Repli : règles déterministes.
            return coordinator.apply_rules(advisors)

    # ------------------------------------------------------------------ #
    # Utilitaire synchrone (pratique pour l'UI / les scripts)
    # ------------------------------------------------------------------ #
    def deliberate_sync(
        self, state: GameState, on_advisor: AdvisorCallback | None = None
    ) -> CouncilDecision:
        """Version bloquante de :meth:`deliberate`."""
        return asyncio.run(self.deliberate(state, on_advisor))
