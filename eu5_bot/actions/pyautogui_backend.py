"""Backend de contrôle réel via ``pyautogui`` (machine de jeu uniquement).

Importé à la demande ; lève ``ImportError`` si ``pyautogui`` est absent, ce qui
déclenche le repli sur ``MockActionBackend``.
"""

from __future__ import annotations

import time

from .backend import ActionBackend

try:
    import pyautogui  # type: ignore
except ImportError as exc:  # pragma: no cover - dépend de la plateforme
    raise ImportError("pyautogui requis pour PyAutoGuiBackend") from exc

try:  # localisation de fenêtre, facultative
    import pygetwindow  # type: ignore
except ImportError:  # pragma: no cover
    pygetwindow = None


class PyAutoGuiBackend(ActionBackend):
    """Contrôle clavier/souris du jeu via pyautogui."""

    available = True

    def __init__(self, process_name: str) -> None:
        self.process_name = process_name
        # Petite pause de sécurité entre les actions.
        pyautogui.PAUSE = 0.15
        pyautogui.FAILSAFE = True

    def focus_game(self) -> bool:  # pragma: no cover - nécessite un bureau Windows
        if pygetwindow is None:
            return False
        for title in ("Europa Universalis V", "EU5"):
            wins = pygetwindow.getWindowsWithTitle(title)
            if wins:
                win = wins[0]
                try:
                    win.activate()
                    time.sleep(0.2)
                    return True
                except Exception:
                    return False
        return False

    def click(self, x: int, y: int) -> None:  # pragma: no cover
        pyautogui.click(x, y)

    def hotkey(self, *keys: str) -> None:  # pragma: no cover
        pyautogui.hotkey(*keys)

    def type_text(self, text: str) -> None:  # pragma: no cover
        pyautogui.typewrite(text, interval=0.03)
