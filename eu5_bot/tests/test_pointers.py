"""Tests des chaînes de pointeurs persistantes (scan inverse + résolution)."""

from eu5_bot.memory.backend import MockMemoryBackend
from eu5_bot.memory.pointers import PointerScanner
from eu5_bot.memory.reader import GameStateReader
from eu5_bot.memory.scanner import MemoryScanner


def test_pointer_scan_finds_static_chain():
    backend = MockMemoryBackend()
    backend.attach()
    addr = backend.address_of("tresor")
    chain = PointerScanner(backend).scan(addr)
    assert chain is not None
    # Le pointeur statique du module pointe vers la struct éco (offset tresor=0).
    assert chain.static_offset == backend._PTR_ECO
    assert chain.offsets == [0]
    # La chaîne se résout exactement vers l'adresse cible.
    assert backend.resolve_chain(backend.module_base(), chain) == addr


def test_pointer_chain_persists_across_relaunch():
    backend = MockMemoryBackend()
    backend.attach()
    mmap = MemoryScanner(backend).scan()
    sig = mmap.signatures["tresor"]
    assert sig.pointer_chain is not None

    old_addr = sig.address
    backend.relaunch()  # simule l'ASLR : les adresses absolues changent
    new_addr = backend.address_of("tresor")
    assert new_addr != old_addr  # l'adresse absolue mémorisée est devenue obsolète

    # La chaîne de pointeurs, elle, résout toujours la bonne (nouvelle) adresse.
    resolved = backend.resolve_chain(mmap.module_base, sig.pointer_chain)
    assert resolved == new_addr


def test_reader_follows_pointer_chain_after_relaunch():
    backend = MockMemoryBackend()
    backend.attach()
    mmap = MemoryScanner(backend).scan()
    reader = GameStateReader(backend, mmap)

    reader.read()  # session initiale
    backend.relaunch()
    state = reader.read()  # après "relance" : doit suivre la chaîne de pointeurs

    expected = backend.read_typed(backend.address_of("tresor"), "f64")
    assert abs(state.tresor - expected) < 1e-3
    assert state.tresor > 0
