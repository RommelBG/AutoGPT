"""Point d'entrée du bot autonome EU5.

Usage :
    python -m eu5_bot.main                 # lance l'interface desktop
    python -m eu5_bot.main --headless       # boucle console (sans UI)
    python -m eu5_bot.main --headless -n 3  # n cycles puis arrêt
    python -m eu5_bot.main --rescan         # force le rescan mémoire puis quitte

Le mode headless est utile sur un serveur sans affichage (ou pour les démos) :
il lit l'état, fait délibérer le Conseil et journalise la décision à chaque
cycle, sans interface graphique.
"""

from __future__ import annotations

import argparse
import json
import sys

from .bot import BotController
from .config import load_config


def _print_decision(bot: BotController) -> None:
    decision = bot.tick_once()
    state = bot.last_state
    print("=" * 72)
    if state:
        print(f"[{state.date}] trésor={state.tresor:,.0f}  "
              f"revenu={state.revenu_mensuel:.1f}  inflation={state.inflation:.2f}%  "
              f"menace={state.menace_militaire}")
    for a in decision.advisors:
        print(f"  {a.source:5s} {a.advisor:13s} : "
              f"{json.dumps(a.data, ensure_ascii=False)}")
    flag = "BLOQUÉE" if decision.bloque else "DÉCISION"
    print(f"  >>> {flag} (consensus {decision.consensus}%) : {decision.decision_finale}")
    if decision.bloque:
        print(f"      raison : {decision.raison_blocage}")


def _calibrate(bot: BotController, field: str) -> int:
    """Scan différentiel interactif d'un champ sur le jeu réel.

    L'utilisateur saisit la valeur affichée à l'écran (ex. le trésor) ; entre
    deux passes, il laisse le jeu faire évoluer cette valeur. Le scan réduit les
    candidats jusqu'à isoler l'adresse, puis l'enregistre dans la carte mémoire.
    """
    from .memory.scanner import SCAN_PLAN, MemoryScanner
    from .models import MemorySignature

    if field not in SCAN_PLAN:
        print(f"Champ inconnu '{field}'. Choix : {', '.join(SCAN_PLAN)}")
        return 2
    vtype = SCAN_PLAN[field]
    scanner = MemoryScanner(bot.memory_backend, bot.config.process_name)

    def ask_value(_f: str):
        raw = input(f"Valeur actuelle de '{field}' affichée dans le jeu (vide = stop) : ").strip()
        if not raw:
            return None
        try:
            return float(raw) if vtype.startswith("f") else int(raw)
        except ValueError:
            print("  valeur non numérique, ignorée.")
            return None

    def settle() -> None:
        input("Laissez le jeu faire évoluer la valeur, puis appuyez sur Entrée…")

    print(f"Calibration du champ '{field}' ({vtype}). Tolérance flottante activée.")
    tol = 0.5 if vtype.startswith("f") else 0.0
    candidates = scanner.scan_field(field, vtype, None, ask_value, settle, max_passes=12, tolerance=tol)
    if not candidates:
        print("Aucune adresse trouvée (valeurs insuffisantes ou jeu non lancé).")
        return 1

    base = bot.memory_backend.module_base()
    addr = candidates[0]
    bot.ensure_memory_map()  # charge/initialise la carte avant d'y écrire
    assert bot.memory_map is not None
    bot.memory_map.signatures[field] = MemorySignature(
        field=field, address=addr, offsets=[addr - base],
        pattern=scanner._signature_around(addr), value_type=vtype,
        candidates=candidates[:8],
        confidence=1.0 if len(candidates) == 1 else round(max(0.0, 1 - (len(candidates) - 1) * 0.2), 3),
    )
    from .config import MEMORY_MAP_PATH

    bot.memory_map.save(MEMORY_MAP_PATH)
    print(f"'{field}' calibré : {len(candidates)} candidat(s), adresse retenue "
          f"0x{addr:x}. Carte mise à jour.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bot autonome EU5 — Conseil LLM")
    parser.add_argument("--headless", action="store_true", help="boucle console sans interface")
    parser.add_argument("-n", "--cycles", type=int, default=0,
                        help="nombre de cycles en headless (0 = infini)")
    parser.add_argument("--rescan", action="store_true", help="force le rescan mémoire puis quitte")
    parser.add_argument("--calibrate", metavar="CHAMP",
                        help="scan différentiel interactif d'un champ (ex. tresor) puis quitte")
    args = parser.parse_args(argv)

    config = load_config()
    bot = BotController(config)

    if args.calibrate:
        return _calibrate(bot, args.calibrate)

    if args.rescan:
        mmap = bot.force_rescan()
        print(f"Rescan terminé : {len(mmap.signatures)} adresses cartographiées "
              f"({bot.scan_status}).")
        return 0

    if args.headless:
        bot.ensure_memory_map()
        print(f"Scan : {bot.scan_status} — "
              f"{len(bot.memory_map.signatures) if bot.memory_map else 0} adresses.")
        try:
            count = 0
            while args.cycles == 0 or count < args.cycles:
                _print_decision(bot)
                count += 1
                if args.cycles == 0:
                    import time

                    time.sleep(config.tick_seconds)
        except KeyboardInterrupt:
            print("\nArrêt demandé.")
        finally:
            bot.shutdown()
        return 0

    # Mode interface desktop.
    try:
        from .ui import run_app
    except Exception as exc:  # tkinter indisponible
        print(f"Interface indisponible ({exc}). Utilisez --headless.", file=sys.stderr)
        return 1
    run_app(bot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
