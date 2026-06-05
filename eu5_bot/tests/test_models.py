"""Tests des structures de données et de la (dé)sérialisation de la carte mémoire."""

from eu5_bot.models import (
    GameState,
    MemoryMap,
    MemorySignature,
    PointerChain,
    Province,
    ProvinceLayout,
)


def test_gamestate_revenu_net():
    s = GameState(revenu_mensuel=42.0, depenses_mensuelles=30.0)
    assert s.revenu_net == 12.0


def test_gamestate_prompt_json_roundtrip():
    s = GameState(tresor=500.0, provinces=[Province("Capitale", 24)])
    txt = s.to_prompt_json()
    assert "Capitale" in txt and "tresor" in txt


def test_memory_map_save_load(tmp_path):
    mmap = MemoryMap(process_name="eu5.exe", module_base=0x140000000)
    mmap.signatures["tresor"] = MemorySignature(
        field="tresor", address=0x140000100, value_type="f64", offsets=[0x100]
    )
    path = tmp_path / "map.json"
    mmap.save(path)

    loaded = MemoryMap.load(path)
    assert loaded is not None
    assert loaded.process_name == "eu5.exe"
    assert "tresor" in loaded.signatures
    assert loaded.signatures["tresor"].address == 0x140000100
    assert loaded.signatures["tresor"].value_type == "f64"


def test_memory_map_load_missing(tmp_path):
    assert MemoryMap.load(tmp_path / "absent.json") is None


def test_memory_map_roundtrip_with_pointer_chain_and_provinces(tmp_path):
    mmap = MemoryMap(process_name="eu5.exe", module_base=0x140000000)
    mmap.signatures["tresor"] = MemorySignature(
        field="tresor", address=0x140010100, value_type="f64",
        pointer_chain=PointerChain(static_offset=0x40, offsets=[0]),
    )
    mmap.province_layout = ProvinceLayout(
        base_address=0x140012000, stride=0x80, count=4,
        field_offsets={"developpement": 0, "slots_disponibles": 4},
        field_types={"developpement": "i32", "slots_disponibles": "i32"},
        pointer_chain=PointerChain(static_offset=0x60, offsets=[0]),
    )
    path = tmp_path / "map.json"
    mmap.save(path)

    loaded = MemoryMap.load(path)
    assert loaded is not None
    sig = loaded.signatures["tresor"]
    assert sig.pointer_chain is not None
    assert sig.pointer_chain.static_offset == 0x40
    assert sig.pointer_chain.offsets == [0]

    pl = loaded.province_layout
    assert pl is not None
    assert pl.count == 4 and pl.stride == 0x80
    assert pl.field_offsets["slots_disponibles"] == 4
    assert pl.pointer_chain.static_offset == 0x60
