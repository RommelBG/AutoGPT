"""Exécution des décisions du Conseil dans le jeu (clics, raccourcis)."""

from .backend import ActionBackend, MockActionBackend, open_action_backend
from .executor import ActionExecutor

__all__ = [
    "ActionBackend",
    "MockActionBackend",
    "open_action_backend",
    "ActionExecutor",
]
