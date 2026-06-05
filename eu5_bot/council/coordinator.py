"""Coordinateur final du Conseil.

Le coordinateur produit la décision exécutable à partir des 4 réponses des
conseillers. Deux niveaux :

1. Un appel LLM (Claude Sonnet 4.6) qui synthétise une décision — utilisé quand
   une clé Anthropic est disponible.
2. Un *moteur de règles déterministe* qui implémente les règles dures du brief.
   Il sert à la fois de repli hors-ligne et de garde-fou : même si le LLM rend
   une décision, les règles 1 (veto Stratège) et 2 (Contradicteur ROUGE) sont
   réappliquées pour garantir qu'une décision dangereuse est bloquée.
"""

from __future__ import annotations

from typing import Any

from ..models import AdvisorResponse, CouncilDecision


def _by_name(advisors: list[AdvisorResponse]) -> dict[str, dict[str, Any]]:
    return {a.advisor: a.data for a in advisors}


def apply_rules(advisors: list[AdvisorResponse]) -> CouncilDecision:
    """Décision déterministe selon les 4 règles du coordinateur (brief).

    1. Veto Stratège (veto: true) → bloquer.
    2. Contradicteur ROUGE → suspendre.
    3. 3 conseillers alignés sur 4 → exécuter.
    4. Égalité → privilégier l'avis du Trésorier.
    """
    data = _by_name(advisors)
    tres = data.get("Trésorier", {})
    cons = data.get("Constructeur", {})
    strat = data.get("Stratège", {})
    contra = data.get("Contradicteur", {})

    province = str(cons.get("province_cible", ""))
    action = str(cons.get("batiment_recommande", ""))

    # Règle 1 : veto du Stratège.
    if strat.get("veto") is True:
        return CouncilDecision(
            decision_finale="Décision bloquée par veto stratégique",
            province=province,
            action=action,
            consensus=_consensus(advisors),
            bloque=True,
            raison_blocage=str(strat.get("raison_veto") or "Veto du Stratège"),
            prochaine_evaluation="dans 1 tour",
            advisors=advisors,
        )

    # Règle 2 : alerte ROUGE du Contradicteur.
    if str(contra.get("niveau_alerte", "")).upper() == "ROUGE":
        return CouncilDecision(
            decision_finale="Décision suspendue : risque critique signalé",
            province=province,
            action=action,
            consensus=_consensus(advisors),
            bloque=True,
            raison_blocage=str(contra.get("argument") or "Alerte ROUGE du Contradicteur"),
            prochaine_evaluation="dans 1 tour",
            advisors=advisors,
        )

    # Règles 3 & 4 : alignement / repli sur le Trésorier.
    aligned = _count_aligned(tres, cons, strat, contra)
    if aligned >= 3:
        decision = f"Construire {action} dans {province}".strip()
    else:
        # Égalité → on suit la recommandation du Trésorier.
        decision = str(tres.get("recommandation") or f"Construire {action} dans {province}")

    return CouncilDecision(
        decision_finale=decision or "Aucune action ce tour",
        province=province,
        action=action,
        consensus=_consensus(advisors),
        bloque=False,
        raison_blocage="",
        prochaine_evaluation="dans 3 tours",
        advisors=advisors,
    )


def _count_aligned(tres, cons, strat, contra) -> int:
    """Compte les conseillers favorables à une action de construction."""
    votes = 0
    if str(tres.get("statut_financier", "")).upper() in ("SAIN", "FRAGILE"):
        votes += 1
    if str(cons.get("priorite", "")).upper() in ("HAUTE", "MOYENNE"):
        votes += 1
    if str(strat.get("alignement_objectif", "")).upper() in ("OPTIMAL", "ACCEPTABLE"):
        votes += 1
    if str(contra.get("niveau_alerte", "")).upper() in ("VERT", "ORANGE"):
        votes += 1
    return votes


def _consensus(advisors: list[AdvisorResponse]) -> int:
    """Consensus = moyenne des confiances déclarées (0-100)."""
    confs = [int(a.data.get("confiance", 0) or 0) for a in advisors if a.ok]
    return int(sum(confs) / len(confs)) if confs else 0


def merge_llm_decision(
    llm_data: dict[str, Any], advisors: list[AdvisorResponse]
) -> CouncilDecision:
    """Construit une ``CouncilDecision`` depuis la sortie LLM du coordinateur,
    puis réapplique les garde-fous (veto / ROUGE) par sécurité."""
    decision = CouncilDecision(
        decision_finale=str(llm_data.get("decision_finale", "")),
        province=str(llm_data.get("province", "")),
        action=str(llm_data.get("action", "")),
        consensus=int(llm_data.get("consensus", 0) or 0),
        bloque=bool(llm_data.get("bloque", False)),
        raison_blocage=str(llm_data.get("raison_blocage") or ""),
        prochaine_evaluation=str(llm_data.get("prochaine_evaluation", "")),
        advisors=advisors,
    )
    # Garde-fous : un veto ou une alerte ROUGE force le blocage même si le LLM
    # a proposé d'exécuter.
    safety = apply_rules(advisors)
    if safety.bloque and not decision.bloque:
        decision.bloque = True
        decision.raison_blocage = safety.raison_blocage
        decision.decision_finale = safety.decision_finale
    return decision
