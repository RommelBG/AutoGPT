"""Tests du scan mémoire différentiel et de la lecture d'état (backend mock)."""

from eu5_bot.memory.backend import MockMemoryBackend
from eu5_bot.memory.reader import GameStateReader
from eu5_bot.memory.scanner import SCAN_PLAN, MemoryScanner


def test_enum_regions_covers_fields():
    backend = MockMemoryBackend()
    backend.attach()
    regions = backend.enum_regions()
    assert regions
    base, size = regions[0]
    assert base <= backend.address_of("tresor") < base + size


def test_scan_value_finds_all_occurrences_including_decoys():
    from eu5_bot.memory.scanner import _encode

    backend = MockMemoryBackend()
    backend.attach()
    real = backend.address_of("tresor")
    val = backend.read_typed(real, "f64")
    # Le scan complet trouve le vrai champ + ses 2 leurres (mêmes octets).
    hits = backend.scan_value(_encode(val, "f64"))
    assert real in hits
    assert len(hits) >= 3


def test_differential_scan_isolates_address():
    backend = MockMemoryBackend()
    backend.attach()
    scanner = MemoryScanner(backend)
    real = backend.address_of("tresor")

    val = backend.read_typed(real, "f64")
    candidates = scanner.first_scan(val, "f64")
    assert real in candidates
    assert len(candidates) >= 3  # ambigu : vrai champ + leurres

    # La valeur évolue ; les leurres restent figés.
    backend.advance(120.0)
    new_val = backend.read_typed(real, "f64")
    assert new_val != val

    reduced = scanner.next_scan(candidates, new_val, "f64")
    assert reduced == [real]  # le scan différentiel a isolé la bonne adresse


def test_full_scan_resolves_tresor_uniquely():
    backend = MockMemoryBackend()
    backend.attach()
    mmap = MemoryScanner(backend).scan()
    sig = mmap.signatures["tresor"]
    assert sig.address == backend.address_of("tresor")
    assert sig.confidence == 1.0
    assert sig.candidates == [backend.address_of("tresor")]


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
