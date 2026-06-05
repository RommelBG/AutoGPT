"""Tests du moteur de règles déterministe du coordinateur (règles du brief)."""

from eu5_bot.council import coordinator
from eu5_bot.models import AdvisorResponse


def _advisors(tres=None, cons=None, strat=None, contra=None):
    return [
        AdvisorResponse("Trésorier", tres or {"statut_financier": "SAIN", "confiance": 80}),
        AdvisorResponse("Constructeur", cons or {
            "province_cible": "Capitale", "batiment_recommande": "marché",
            "priorite": "HAUTE", "confiance": 80}),
        AdvisorResponse("Stratège", strat or {
            "alignement_objectif": "OPTIMAL", "veto": False, "confiance": 70}),
        AdvisorResponse("Contradicteur", contra or {
            "niveau_alerte": "VERT", "confiance": 60}),
    ]


def test_rule1_strategic_veto_blocks():
    advisors = _advisors(strat={"alignement_objectif": "CONTRE-PRODUCTIF",
                                 "veto": True, "raison_veto": "guerre imminente",
                                 "confiance": 90})
    d = coordinator.apply_rules(advisors)
    assert d.bloque is True
    assert "guerre imminente" in d.raison_blocage


def test_rule2_red_alert_suspends():
    advisors = _advisors(contra={"niveau_alerte": "ROUGE",
                                  "argument": "trésor insuffisant", "confiance": 85})
    d = coordinator.apply_rules(advisors)
    assert d.bloque is True
    assert "trésor insuffisant" in d.raison_blocage


def test_rule3_three_aligned_executes():
    d = coordinator.apply_rules(_advisors())
    assert d.bloque is False
    assert "marché" in d.decision_finale
    assert d.province == "Capitale"


def test_consensus_is_mean_of_confidences():
    advisors = _advisors()
    d = coordinator.apply_rules(advisors)
    # (80 + 80 + 70 + 60) / 4 = 72
    assert d.consensus == 72


def test_merge_llm_decision_respects_safety_veto():
    # Le LLM propose d'exécuter, mais un veto stratégique doit forcer le blocage.
    advisors = _advisors(strat={"alignement_objectif": "CONTRE-PRODUCTIF",
                                 "veto": True, "raison_veto": "menace", "confiance": 90})
    llm = {"decision_finale": "Construire marché", "province": "Capitale",
           "action": "marché", "consensus": 70, "bloque": False}
    d = coordinator.merge_llm_decision(llm, advisors)
    assert d.bloque is True
    assert "menace" in d.raison_blocage
