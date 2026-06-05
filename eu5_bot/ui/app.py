"""Interface desktop tkinter à deux panneaux.

PANNEAU GAUCHE — état du jeu en temps réel (trésor, revenu, inflation, dernières
adresses lues, statut du scan).
PANNEAU DROIT — activité du Conseil (réponse de chaque conseiller, décision du
coordinateur, historique des 20 dernières décisions).

Contrôles : START / PAUSE / STOP, FORCER RESCAN, slider de vitesse 1x–5x,
toggles par conseiller, export du log en .txt.

Les callbacks du bot arrivent depuis un thread de travail ; ils sont sérialisés
vers le thread UI via une ``queue`` consultée périodiquement avec ``after``.
"""

from __future__ import annotations

import json
import queue
import time
from pathlib import Path

from ..bot import BotController
from ..models import AdvisorResponse, CouncilDecision, GameState


def run_app(bot: BotController | None = None) -> None:
    """Lance l'application desktop. Crée un ``BotController`` si non fourni."""
    import tkinter as tk
    from tkinter import ttk, filedialog

    bot = bot or BotController()
    events: "queue.Queue[tuple[str, object]]" = queue.Queue()

    # Relie les callbacks du bot à la file d'événements (thread-safe).
    bot.on_state = lambda s: events.put(("state", s))
    bot.on_advisor = lambda a: events.put(("advisor", a))
    bot.on_decision = lambda d: events.put(("decision", d))
    bot.on_action = lambda r: events.put(("action", r))
    bot.on_status = lambda st: events.put(("status", st))
    bot.on_scan_progress = lambda f, i, n: events.put(("scan", (f, i, n)))

    root = tk.Tk()
    root.title("Bot Autonome EU5 — Conseil LLM")
    root.geometry("1100x680")

    # ----- barre de contrôles ----- #
    controls = ttk.Frame(root, padding=8)
    controls.pack(side=tk.TOP, fill=tk.X)

    def do_start():
        bot.start()

    def do_pause():
        bot.pause() if not bot._paused else bot.resume()

    def do_stop():
        bot.stop()

    def do_rescan():
        events.put(("status", "rescan forcé…"))
        threading_run(bot.force_rescan)

    ttk.Button(controls, text="▶ START", command=do_start).pack(side=tk.LEFT, padx=3)
    ttk.Button(controls, text="⏸ PAUSE", command=do_pause).pack(side=tk.LEFT, padx=3)
    ttk.Button(controls, text="⏹ STOP", command=do_stop).pack(side=tk.LEFT, padx=3)
    ttk.Button(controls, text="🔄 FORCER RESCAN", command=do_rescan).pack(side=tk.LEFT, padx=3)

    ttk.Label(controls, text="Vitesse :").pack(side=tk.LEFT, padx=(20, 3))
    speed = ttk.Scale(
        controls, from_=1, to=5, orient=tk.HORIZONTAL, length=120,
        command=lambda v: bot.set_speed(int(float(v))),
    )
    speed.set(1)
    speed.pack(side=tk.LEFT)
    speed_lbl = ttk.Label(controls, text="1x")
    speed_lbl.pack(side=tk.LEFT, padx=3)
    speed.configure(command=lambda v: (bot.set_speed(int(float(v))),
                                       speed_lbl.config(text=f"{int(float(v))}x")))

    # ----- toggles conseillers ----- #
    toggles = ttk.Frame(root, padding=(8, 0))
    toggles.pack(side=tk.TOP, fill=tk.X)
    ttk.Label(toggles, text="Conseillers :").pack(side=tk.LEFT)
    for adv in bot.config.advisors:
        var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            toggles, text=adv.name, variable=var,
            command=lambda n=adv.name, v=var: bot.set_advisor_enabled(n, v.get()),
        ).pack(side=tk.LEFT, padx=4)

    # ----- panneaux ----- #
    panes = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
    panes.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    # Gauche : état du jeu
    left = ttk.LabelFrame(panes, text="ÉTAT DU JEU (temps réel)", padding=8)
    panes.add(left, weight=1)
    state_text = tk.Text(left, height=20, width=44, font=("Consolas", 10))
    state_text.pack(fill=tk.BOTH, expand=True)
    status_var = tk.StringVar(value="Statut scan : non démarré")
    ttk.Label(left, textvariable=status_var, foreground="#555").pack(anchor=tk.W, pady=(6, 0))

    # Droite : Conseil
    right = ttk.LabelFrame(panes, text="ACTIVITÉ DU CONSEIL", padding=8)
    panes.add(right, weight=2)
    council_text = tk.Text(right, height=24, font=("Consolas", 10))
    council_text.pack(fill=tk.BOTH, expand=True)

    # ----- export log ----- #
    def export_log():
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Texte", "*.txt")],
            initialfile=f"eu5_bot_log_{int(time.time())}.txt",
        )
        if path:
            Path(path).write_text(council_text.get("1.0", tk.END), encoding="utf-8")

    ttk.Button(controls, text="💾 Export log .txt", command=export_log).pack(side=tk.RIGHT, padx=3)

    # ----- rendu ----- #
    def render_state(s: GameState) -> None:
        state_text.delete("1.0", tk.END)
        lines = [
            f"Date          : {s.date}",
            f"Trésor        : {s.tresor:,.0f} or",
            f"Revenu mensuel: {s.revenu_mensuel:,.1f}  (net {s.revenu_net:+.1f})",
            f"  taxes={s.revenu_taxes:.1f} prod={s.revenu_production:.1f} "
            f"comm={s.revenu_commerce:.1f} sujets={s.revenu_sujets:.1f}",
            f"Dépenses      : {s.depenses_mensuelles:,.1f}",
            f"Inflation     : {s.inflation:.2f}%",
            f"Stabilité     : {s.stabilite:+d}",
            f"Dettes        : {s.dettes:,.0f}  (intérêts {s.interets_mensuels:.1f}/mois)",
            f"Manpower      : {s.manpower:,}",
            f"Puissance/Menace: {s.score_puissance} / {s.menace_militaire}",
            "",
            "Provinces :",
        ]
        for p in s.provinces:
            lines.append(f"  • {p.nom} (dev {p.developpement}, {len(p.batiments)} bât., "
                         f"{p.slots_disponibles} slots)")
        lines.append("")
        lines.append("Dernières adresses lues :")
        if bot.memory_map:
            for fld, sig in list(bot.memory_map.signatures.items())[:6]:
                lines.append(f"  {fld:18s} @ 0x{sig.address:012x} ({sig.value_type})")
        state_text.insert(tk.END, "\n".join(lines))

    def append_council(text: str) -> None:
        council_text.insert(tk.END, text + "\n")
        council_text.see(tk.END)

    def render_advisor(a: AdvisorResponse) -> None:
        tag = {"llm": "🟢", "mock": "🟡", "error": "🔴"}.get(a.source, "•")
        append_council(f"{tag} {a.advisor} [{a.source}, {a.latency_s}s]: "
                       f"{json.dumps(a.data, ensure_ascii=False)}")

    def render_decision(d: CouncilDecision) -> None:
        flag = "⛔ BLOQUÉE" if d.bloque else "✅ DÉCISION"
        append_council(f"━━ {flag} (consensus {d.consensus}%) ━━")
        append_council(f"   → {d.decision_finale}")
        if d.bloque:
            append_council(f"   raison : {d.raison_blocage}")
        append_council(f"   prochaine éval : {d.prochaine_evaluation}\n")

    def render_action(r: dict) -> None:
        if r.get("executed"):
            append_council(f"   🎮 exécuté : {' | '.join(r.get('steps', []))}\n")
        else:
            append_council(f"   ⏭ non exécuté : {r.get('reason', '')}\n")

    # ----- pompe d'événements ----- #
    def pump() -> None:
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == "state":
                    render_state(payload)        # type: ignore[arg-type]
                elif kind == "advisor":
                    render_advisor(payload)      # type: ignore[arg-type]
                elif kind == "decision":
                    render_decision(payload)     # type: ignore[arg-type]
                elif kind == "action":
                    render_action(payload)       # type: ignore[arg-type]
                elif kind == "status":
                    status_var.set(f"Statut scan : {payload}")
                elif kind == "scan":
                    f, i, n = payload  # type: ignore[misc]
                    status_var.set(f"Scan : {f} ({i}/{n})")
        except queue.Empty:
            pass
        root.after(120, pump)

    def threading_run(fn):
        import threading

        threading.Thread(target=fn, daemon=True).start()

    # Charge la carte mémoire au démarrage (en tâche de fond).
    threading_run(bot.ensure_memory_map)
    root.after(120, pump)

    def on_close():
        bot.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
