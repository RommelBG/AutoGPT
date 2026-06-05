"""Exécuteur d'actions : traduit une ``CouncilDecision`` en gestes dans le jeu.

Le périmètre initial (cf. brief) est la construction de bâtiments. Le mapping
clic/raccourci est volontairement paramétrable car les coordonnées exactes de
l'UI d'EU5 dépendent de la résolution et de la version ; ils sont regroupés dans
``UI_HINTS`` pour être calibrés facilement.
"""

from __future__ import annotations

from ..models import CouncilDecision
from .backend import ActionBackend

# Indices d'interface (à calibrer selon la résolution / version du jeu).
# Coordonnées factices par défaut : sûres avec le backend mock.
UI_HINTS = {
    "open_province_search": ("f",),     # raccourci ouverture recherche province
    "open_build_menu": ("b",),          # raccourci menu construction
    "confirm_button": (960, 700),       # bouton de confirmation
}


class ActionExecutor:
    """Exécute la décision du Conseil dans le jeu."""

    def __init__(self, backend: ActionBackend) -> None:
        self.backend = backend

    def execute(self, decision: CouncilDecision) -> dict:
        """Exécute la décision. Renvoie un compte rendu structuré.

        Une décision bloquée n'entraîne aucune action dans le jeu.
        """
        if decision.bloque:
            return {
                "executed": False,
                "reason": decision.raison_blocage or "Décision bloquée",
                "steps": [],
            }
        if not decision.action or not decision.province:
            return {
                "executed": False,
                "reason": "Décision sans action/province exploitable",
                "steps": [],
            }

        steps: list[str] = []
        if not self.backend.focus_game():
            steps.append("avertissement: fenêtre du jeu non focalisée")

        # 1. Rechercher / sélectionner la province cible.
        self.backend.hotkey(*UI_HINTS["open_province_search"])
        self.backend.type_text(decision.province)
        steps.append(f"sélection province: {decision.province}")

        # 2. Ouvrir le menu de construction.
        self.backend.hotkey(*UI_HINTS["open_build_menu"])
        steps.append("ouverture menu construction")

        # 3. Choisir le bâtiment puis confirmer.
        self.backend.type_text(decision.action)
        cx, cy = UI_HINTS["confirm_button"]
        self.backend.click(cx, cy)
        steps.append(f"construction confirmée: {decision.action}")

        return {"executed": True, "reason": "", "steps": steps}
