"""Abstraction du contrôle du jeu (clavier / souris).

``ActionBackend`` est l'interface dont dépend l'exécuteur. Deux implémentations :

    - ``PyAutoGuiBackend`` : contrôle réel via ``pyautogui`` (machine de jeu).
    - ``MockActionBackend`` : journalise les actions sans rien cliquer — sûr pour
      le développement et les tests. C'est le défaut hors-Windows.
"""

from __future__ import annotations

import abc


class ActionBackend(abc.ABC):
    """Interface de contrôle du jeu."""

    available: bool = False

    @abc.abstractmethod
    def focus_game(self) -> bool:
        """Met la fenêtre du jeu au premier plan. True si réussi."""

    @abc.abstractmethod
    def click(self, x: int, y: int) -> None:
        """Clique aux coordonnées écran données."""

    @abc.abstractmethod
    def hotkey(self, *keys: str) -> None:
        """Envoie un raccourci clavier (ex. 'b' pour le menu Bâtiments)."""

    @abc.abstractmethod
    def type_text(self, text: str) -> None:
        """Saisit du texte (ex. recherche d'une province)."""

    def log(self) -> list[str]:
        """Historique des actions (utile pour le mock et les tests)."""
        return []


class MockActionBackend(ActionBackend):
    """Backend de simulation : enregistre les actions au lieu de les exécuter."""

    available = True

    def __init__(self) -> None:
        self._log: list[str] = []

    def focus_game(self) -> bool:
        self._log.append("focus_game()")
        return True

    def click(self, x: int, y: int) -> None:
        self._log.append(f"click({x}, {y})")

    def hotkey(self, *keys: str) -> None:
        self._log.append(f"hotkey({'+'.join(keys)})")

    def type_text(self, text: str) -> None:
        self._log.append(f"type_text({text!r})")

    def log(self) -> list[str]:
        return list(self._log)


def open_action_backend(config) -> ActionBackend:
    """Sélectionne le backend d'action selon la configuration.

    "auto"      : pyautogui si importable, sinon mock.
    "pyautogui" : force pyautogui (lève si indisponible).
    "mock"      : force la simulation.
    """
    mode = config.action_backend
    if mode == "mock":
        return MockActionBackend()
    if mode in ("auto", "pyautogui"):
        try:
            from .pyautogui_backend import PyAutoGuiBackend

            return PyAutoGuiBackend(config.process_name)
        except ImportError:
            if mode == "pyautogui":
                raise RuntimeError("pyautogui n'est pas installé (backend 'pyautogui').")
    return MockActionBackend()
