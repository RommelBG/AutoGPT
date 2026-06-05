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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bot autonome EU5 — Conseil LLM")
    parser.add_argument("--headless", action="store_true", help="boucle console sans interface")
    parser.add_argument("-n", "--cycles", type=int, default=0,
                        help="nombre de cycles en headless (0 = infini)")
    parser.add_argument("--rescan", action="store_true", help="force le rescan mémoire puis quitte")
    args = parser.parse_args(argv)

    config = load_config()
    bot = BotController(config)

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
