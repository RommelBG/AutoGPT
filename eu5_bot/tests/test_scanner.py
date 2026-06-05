"""Tests du scan mémoire et de la lecture d'état sur le backend mock."""

from eu5_bot.memory.backend import MockMemoryBackend
from eu5_bot.memory.reader import GameStateReader
from eu5_bot.memory.scanner import SCAN_PLAN, MemoryScanner


def test_mock_backend_scan_finds_addresses():
    backend = MockMemoryBackend()
    backend.attach()
    scanner = MemoryScanner(backend, "eu5.exe")
    mmap = scanner.scan()
    # Tous les champs économiques planifiés doivent être localisés.
    assert set(mmap.signatures) == set(SCAN_PLAN)
    for sig in mmap.signatures.values():
        assert sig.address != 0
        assert sig.pattern  # une signature AOB a été construite


def test_load_or_scan_uses_cache(tmp_path):
    backend = MockMemoryBackend()
    backend.attach()
    scanner = MemoryScanner(backend, "eu5.exe")
    path = tmp_path / "map.json"

    mmap1, status1 = scanner.load_or_scan(path)
    assert status1 == "scanné"

    mmap2, status2 = scanner.load_or_scan(path)
    assert status2 == "chargé"
    assert set(mmap1.signatures) == set(mmap2.signatures)


def test_force_rescan(tmp_path):
    backend = MockMemoryBackend()
    backend.attach()
    scanner = MemoryScanner(backend, "eu5.exe")
    path = tmp_path / "map.json"
    scanner.load_or_scan(path)
    _, status = scanner.load_or_scan(path, force=True)
    assert status == "scanné"


def test_reader_reads_coherent_state():
    backend = MockMemoryBackend()
    backend.attach()
    mmap = MemoryScanner(backend, "eu5.exe").scan()
    state = GameStateReader(backend, mmap).read()

    assert state.tresor >= 0
    # Le revenu mensuel est la somme des quatre composantes.
    expected = (state.revenu_taxes + state.revenu_production
                + state.revenu_commerce + state.revenu_sujets)
    assert abs(state.revenu_mensuel - expected) < 1e-3
    assert state.provinces  # le mock fournit des provinces
