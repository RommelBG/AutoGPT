"""Tests du contrôleur principal en mode mock (mémoire + actions simulées)."""

from eu5_bot.bot import BotController
from eu5_bot.config import Config


def _mock_config() -> Config:
    return Config(memory_backend="mock", action_backend="mock")


def test_tick_once_produces_decision_and_action(tmp_path, monkeypatch):
    monkeypatch.setattr("eu5_bot.bot.MEMORY_MAP_PATH", tmp_path / "map.json")
    bot = BotController(_mock_config())
    bot.ensure_memory_map()
    assert bot.scan_status in ("scan terminé", "chargé depuis le cache")

    decision = bot.tick_once()
    assert decision.decision_finale
    # L'exécuteur mock a journalisé des gestes (décision non bloquée).
    assert bot.action_backend.log()
    # L'historique conserve la décision.
    assert bot.history and bot.history[-1] is decision


def test_advisor_toggle_disables_advisor(tmp_path, monkeypatch):
    monkeypatch.setattr("eu5_bot.bot.MEMORY_MAP_PATH", tmp_path / "map.json")
    bot = BotController(_mock_config())
    bot.set_advisor_enabled("Stratège", False)
    assert all(a.enabled for a in bot.config.advisors if a.name != "Stratège")
    assert not next(a for a in bot.config.advisors if a.name == "Stratège").enabled

    bot.ensure_memory_map()
    decision = bot.tick_once()
    # Seuls 3 conseillers actifs participent.
    assert {a.advisor for a in decision.advisors} == {
        "Trésorier", "Constructeur", "Contradicteur"}


def test_date_progresses_across_ticks(tmp_path, monkeypatch):
    monkeypatch.setattr("eu5_bot.bot.MEMORY_MAP_PATH", tmp_path / "map.json")
    bot = BotController(_mock_config())
    bot.ensure_memory_map()
    bot.tick_once()
    first = bot.last_state.date
    bot.tick_once()
    second = bot.last_state.date
    assert first != second
