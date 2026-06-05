"""Tests du scan du tableau de provinces (base/stride/count/offsets + lecture)."""

from eu5_bot.memory.backend import MockMemoryBackend
from eu5_bot.memory.provinces import read_provinces
from eu5_bot.memory.reader import GameStateReader
from eu5_bot.memory.scanner import MemoryScanner


def test_province_scan_discovers_layout():
    backend = MockMemoryBackend()
    backend.attach()
    mmap = MemoryScanner(backend).scan()
    layout = mmap.province_layout
    assert layout is not None
    assert layout.count == 4
    assert layout.stride == backend._PROV_STRIDE
    # Offsets de champs découverts par différentiel + vérification de cohérence.
    assert layout.field_offsets["developpement"] == 0x00
    assert layout.field_offsets["slots_disponibles"] == 0x04
    assert layout.field_offsets["nb_batiments"] == 0x08


def test_read_provinces_values():
    backend = MockMemoryBackend()
    backend.attach()
    layout = MemoryScanner(backend).scan().province_layout
    provs = read_provinces(backend, layout, backend.module_base())
    assert len(provs) == 4
    assert provs[0].developpement == 24
    assert provs[0].slots_disponibles == 2
    assert len(provs[0].batiments) == 2  # nb_batiments = 2
    assert provs[3].developpement == 9


def test_province_layout_has_persistent_pointer_chain():
    backend = MockMemoryBackend()
    backend.attach()
    layout = MemoryScanner(backend).scan().province_layout
    assert layout.pointer_chain is not None
    assert layout.pointer_chain.static_offset == backend._PTR_PROV

    backend.relaunch()  # adresses absolues invalidées
    provs = read_provinces(backend, layout, backend.module_base())
    # La lecture suit la chaîne de pointeurs et reste correcte après relance.
    assert provs[0].developpement == 24
    assert provs[3].developpement == 9


def test_public_scan_provinces_with_calibration():
    backend = MockMemoryBackend()
    backend.attach()
    values, types = backend.province_calibration()
    layout = MemoryScanner(backend).scan_provinces(values, types)
    assert layout is not None
    assert layout.count == 4


def test_reader_exposes_provinces_via_layout():
    backend = MockMemoryBackend()
    backend.attach()
    mmap = MemoryScanner(backend).scan()
    state = GameStateReader(backend, mmap).read()
    assert len(state.provinces) == 4
    assert state.provinces[0].nom == "Province 1"
