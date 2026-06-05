"""Contrôleur principal du bot — relie mémoire, Conseil et exécution.

``BotController`` orchestre la boucle PHASE 2 :

    lire l'état (mémoire) → délibérer (Conseil) → exécuter (jeu) → attendre

La boucle tourne dans un thread dédié pour ne pas bloquer l'interface. Des
callbacks permettent à l'UI (ou à un script) de réagir aux événements :
nouvel état lu, réponse d'un conseiller, décision finale, action exécutée.

Contrôles : ``start`` / ``pause`` / ``resume`` / ``stop``, vitesse 1x–5x,
activation/désactivation des conseillers, rescan mémoire forcé.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from .config import Config, MEMORY_MAP_PATH, load_config
from .council import Council
from .actions import ActionExecutor, open_action_backend
from .memory import GameStateReader, MemoryScanner, open_memory_backend
from .models import AdvisorResponse, CouncilDecision, GameState, MemoryMap


class BotController:
    """État, boucle et contrôles du bot autonome."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()

        # Backends (mémoire + action), choisis automatiquement.
        self.memory_backend = open_memory_backend(self.config)
        self.action_backend = open_action_backend(self.config)
        self.council = Council(self.config)
        self.executor = ActionExecutor(self.action_backend)

        # État de scan.
        self.scanner = MemoryScanner(self.memory_backend, self.config.process_name)
        self.memory_map: MemoryMap | None = None
        self.scan_status = "non démarré"
        self.reader: GameStateReader | None = None

        # État de la boucle.
        self.speed = 1
        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Historique des 20 dernières décisions.
        self.history: deque[CouncilDecision] = deque(maxlen=20)
        self.last_state: GameState | None = None
        self._game_date = "1337.1.1"  # date de jeu suivie d'un cycle à l'autre

        # Callbacks d'interface (tous optionnels).
        self.on_state: Callable[[GameState], None] | None = None
        self.on_advisor: Callable[[AdvisorResponse], None] | None = None
        self.on_decision: Callable[[CouncilDecision], None] | None = None
        self.on_action: Callable[[dict], None] | None = None
        self.on_status: Callable[[str], None] | None = None
        self.on_scan_progress: Callable[[str, int, int], None] | None = None

    # ------------------------------------------------------------------ #
    # PHASE 1 — scan mémoire
    # ------------------------------------------------------------------ #
    def ensure_memory_map(self, force: bool = False) -> MemoryMap:
        """Charge la carte mémoire (cache) ou (re)scanne si absente/forcée."""
        self._emit_status("scan mémoire en cours…")
        mmap, status = self.scanner.load_or_scan(
            MEMORY_MAP_PATH, force=force, progress=self._scan_progress
        )
        self.memory_map = mmap
        self.scan_status = "chargé depuis le cache" if status == "chargé" else "scan terminé"
        self.reader = GameStateReader(self.memory_backend, mmap)
        self._emit_status(self.scan_status)
        return mmap

    def force_rescan(self) -> MemoryMap:
        """Bouton « Forcer le rescan mémoire » de l'interface."""
        return self.ensure_memory_map(force=True)

    def _scan_progress(self, field: str, done: int, total: int) -> None:
        if self.on_scan_progress:
            self.on_scan_progress(field, done, total)

    # ------------------------------------------------------------------ #
    # PHASE 2 — boucle de jeu autonome
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Démarre la boucle de décision dans un thread dédié."""
        if self._running:
            return
        if self.reader is None:
            self.ensure_memory_map()
        self._running = True
        self._paused = False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="eu5-bot-loop", daemon=True)
        self._thread.start()
        self._emit_status("démarré")

    def pause(self) -> None:
        self._paused = True
        self._emit_status("en pause")

    def resume(self) -> None:
        self._paused = False
        self._emit_status("repris")

    def stop(self) -> None:
        """Arrête la boucle et attend la fin du thread."""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._emit_status("arrêté")

    def set_speed(self, speed: int) -> None:
        """Règle la vitesse d'exécution (1x à 5x)."""
        self.speed = max(1, min(5, int(speed)))

    def set_advisor_enabled(self, advisor_name: str, enabled: bool) -> None:
        """Active/désactive un conseiller (toggle de l'interface)."""
        for adv in self.config.advisors:
            if adv.name == advisor_name:
                adv.enabled = enabled  # mutation en place (AdvisorConfig mutable)
                return

    def tick_once(self) -> CouncilDecision:
        """Exécute un unique cycle (lecture → délibération → exécution).

        Pratique pour les tests et un mode pas-à-pas.
        """
        assert self.reader is not None, "carte mémoire non initialisée"
        state = self.reader.read()
        self._game_date = self._next_date(self._game_date)
        state.date = self._game_date
        self.last_state = state
        if self.on_state:
            self.on_state(state)

        decision = self.council.deliberate_sync(state, on_advisor=self._emit_advisor)
        self.history.append(decision)
        if self.on_decision:
            self.on_decision(decision)

        report = self.executor.execute(decision)
        if self.on_action:
            self.on_action(report)
        return decision

    # ------------------------------------------------------------------ #
    # Internes
    # ------------------------------------------------------------------ #
    def _loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            if self._paused:
                time.sleep(0.2)
                continue
            try:
                self.tick_once()
            except Exception as exc:  # une erreur de cycle ne tue pas la boucle
                self._emit_status(f"erreur de cycle: {exc}")
            # Vitesse : 1x = tick_seconds, 5x = tick_seconds / 5.
            delay = self.config.tick_seconds / self.speed
            self._stop_event.wait(timeout=delay)

    def _emit_advisor(self, resp: AdvisorResponse) -> None:
        if self.on_advisor:
            self.on_advisor(resp)

    def _emit_status(self, status: str) -> None:
        if self.on_status:
            self.on_status(status)

    def _next_date(self, date: str) -> str:
        """Fait avancer la date de jeu d'un mois à chaque cycle (affichage)."""
        try:
            y, m, d = (int(x) for x in date.split("."))
        except ValueError:
            y, m, d = 1337, 1, 1
        m += 1
        if m > 12:
            m = 1
            y += 1
        return f"{y}.{m}.{d}"

    def shutdown(self) -> None:
        """Libère les ressources (backends)."""
        self.stop()
        try:
            self.memory_backend.close()
        except Exception:
            pass
