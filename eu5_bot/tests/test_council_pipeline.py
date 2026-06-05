"""Tests d'intégration : pipeline complet en mode mock (sans clé API)."""

from eu5_bot.config import Config
from eu5_bot.council import Council
from eu5_bot.council.llm_client import extract_json
from eu5_bot.memory.backend import MockMemoryBackend
from eu5_bot.memory.reader import GameStateReader
from eu5_bot.memory.scanner import MemoryScanner


def test_extract_json_handles_think_and_fences():
    text = "<think>raisonnement…</think>\n```json\n{\"a\": 1, \"b\": {\"c\": 2}}\n```"
    assert extract_json(text) == {"a": 1, "b": {"c": 2}}


def test_full_deliberation_mock(monkeypatch):
    # Pas de clés -> tous les conseillers et le coordinateur sont en mock.
    config = Config()
    backend = MockMemoryBackend()
    backend.attach()
    mmap = MemoryScanner(backend).scan()
    state = GameStateReader(backend, mmap).read()

    decision = Council(config).deliberate_sync(state)
    assert decision.decision_finale
    assert len(decision.advisors) == 4
    assert all(a.source == "mock" for a in decision.advisors)
    # Consensus = moyenne des confiances mock (75, 80, 70, 65) = 72.
    assert decision.consensus == 72


def test_advisor_callback_invoked():
    received = []
    config = Config()
    backend = MockMemoryBackend()
    backend.attach()
    state = GameStateReader(backend, MemoryScanner(backend).scan()).read()
    Council(config).deliberate_sync(state, on_advisor=received.append)
    assert {a.advisor for a in received} == {
        "Trésorier", "Constructeur", "Stratège", "Contradicteur"}
