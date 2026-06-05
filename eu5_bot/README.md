# Bot Autonome EU5 — Conseil LLM

Bot autonome pour **Europa Universalis V** : il lit l'état du jeu directement en
mémoire, le soumet à un **Conseil multi-agents LLM** (4 conseillers + 1
coordinateur), puis exécute la décision dans le jeu — sans intervention humaine.
Périmètre initial : **gestion économique + construction de bâtiments**.

> ⚠️ Outil d'automatisation pour le mode **solo**. La lecture mémoire et le
> contrôle d'entrée ciblent **Windows** avec le jeu lancé. Le projet tourne
> néanmoins partout (Linux/macOS, CI, sans le jeu) grâce à des **backends de
> simulation** : tout le pipeline — scan, Conseil, exécution, interface — est
> développable et testable hors-ligne.

---

## Architecture

```
PHASE 1 — Scan & cartographie mémoire      PHASE 2 — Jeu autonome (boucle)
┌───────────────────────────┐              ┌──────────────────────────────────┐
│ MemoryScanner             │              │  lire l'état (GameStateReader)    │
│  → MemoryMap (JSON cache)  │   ───────▶   │      ↓                            │
│  signatures AOB + offsets  │              │  délibérer (Council)              │
└───────────────────────────┘              │   4 conseillers en parallèle      │
                                            │   + coordinateur final            │
                                            │      ↓                            │
                                            │  exécuter (ActionExecutor)        │
                                            └──────────────────────────────────┘
```

### Le Conseil LLM

| Rôle | Fournisseur (défaut) | Modèle (défaut) |
|------|----------------------|-----------------|
| Conseiller Trésorier | Cerebras | `qwen-3-32b` |
| Conseiller Constructeur | DeepSeek | `deepseek-reasoner` |
| Conseiller Stratège | DeepSeek | `deepseek-reasoner` |
| Conseiller Contradicteur | Cerebras | `qwen-3-32b` |
| **Coordinateur final** | **Anthropic** | **`claude-sonnet-4-6`** |

Les conseillers répondent **en parallèle** ; le coordinateur synthétise une
décision exécutable. Un **moteur de règles déterministe** (cf. `coordinator.py`)
implémente les règles dures du brief et sert de garde-fou même quand le
coordinateur LLM est actif :

1. **Veto du Stratège** (`veto: true`) → décision bloquée.
2. **Contradicteur ROUGE** → décision suspendue.
3. **3 conseillers alignés / 4** → exécution.
4. **Égalité** → on suit l'avis du Trésorier.

Sans clé API, chaque conseiller bascule automatiquement en **mode mock** (réponse
JSON simulée), de sorte qu'un cycle aboutit toujours à une décision.

---

## Installation

```bash
pip install -r eu5_bot/requirements.txt          # cœur (httpx, anthropic, dotenv)
# Sur la machine de jeu Windows, en plus :
pip install pymem pyautogui pygetwindow
cp eu5_bot/.env.example eu5_bot/.env             # puis renseignez vos clés API
```

## Utilisation

```bash
# Interface desktop (deux panneaux + contrôles)
python -m eu5_bot.main

# Boucle console sans interface (serveur / démo) — 3 cycles puis arrêt
python -m eu5_bot.main --headless -n 3

# Forcer un rescan mémoire (après une mise à jour du jeu) puis quitter
python -m eu5_bot.main --rescan
```

### Interface desktop

- **Panneau gauche** : état du jeu en temps réel (trésor, revenu, inflation,
  dettes, manpower, provinces), dernières adresses mémoire lues, statut du scan.
- **Panneau droit** : réponse de chaque conseiller en direct, décision du
  coordinateur, historique des décisions.
- **Contrôles** : `START` / `PAUSE` / `STOP`, `FORCER RESCAN MÉMOIRE`, slider de
  vitesse **1x–5x**, toggle par conseiller, export du log en `.txt`.

---

## Structure du code

```
eu5_bot/
├── main.py              Point d'entrée (UI / headless / rescan)
├── config.py            Configuration (clés API, modèles, options) depuis l'env/.env
├── models.py            Dataclasses : GameState, MemoryMap, AdvisorResponse, CouncilDecision
├── bot.py               BotController : boucle, contrôles, historique, callbacks
├── memory/              PHASE 1 — scan & lecture mémoire
│   ├── backend.py         Interface MemoryBackend + MockMemoryBackend (simulation)
│   ├── pymem_backend.py   Backend réel pymem (Windows, importé à la demande)
│   ├── scanner.py         Scan par valeur + signatures AOB → MemoryMap (cache JSON)
│   └── reader.py          GameStateReader : adresses → GameState
├── council/             PHASE 2 — analyse & décision
│   ├── prompts.py         Prompts système des 4 conseillers + coordinateur (brief)
│   ├── llm_client.py      Appels Cerebras/DeepSeek/Groq (httpx) + Anthropic (SDK) + mock
│   ├── advisors via council.py (4 conseillers en parallèle)
│   ├── coordinator.py     Décision LLM + moteur de règles déterministe (garde-fous)
│   └── council.py         Orchestrateur du cycle de délibération
├── actions/             PHASE 2 — exécution dans le jeu
│   ├── backend.py         Interface ActionBackend + MockActionBackend (journalise)
│   ├── pyautogui_backend.py  Backend réel pyautogui (Windows, à la demande)
│   └── executor.py        CouncilDecision → gestes (sélection province, construction)
├── ui/app.py            Interface desktop tkinter (deux panneaux + contrôles)
└── tests/               Tests pytest (modèles, scan, règles, pipeline mock)
```

### Sélection automatique des backends

`EU5_MEMORY_BACKEND` / `EU5_ACTION_BACKEND` acceptent :
- `auto` (défaut) — backend réel si la lib est installée et le jeu présent,
  sinon repli sur la simulation ;
- `pymem` / `pyautogui` — force le backend réel (erreur si indisponible) ;
- `mock` — force la simulation.

---

## Tests

```bash
python -m pytest eu5_bot/tests -q
```

Les tests couvrent : (dé)sérialisation de la carte mémoire, scan + cache +
rescan sur le backend mock, lecture cohérente de l'état, les 4 règles du
coordinateur, l'extraction JSON robuste (balises `<think>`, fences markdown) et
le pipeline complet en mode mock.

---

## Notes d'implémentation & limites

- **Adresses mémoire réelles** : `SCAN_PLAN` (dans `scanner.py`) liste les champs
  économiques visés. Le scan localise une valeur de référence puis dérive une
  **signature AOB** des octets voisins pour résister aux patchs. Les *valeurs de
  référence* réelles doivent être calibrées sur la machine de jeu (l'API
  `MemoryScanner.scan(reference_values=...)` accepte cette calibration).
- **Coordonnées d'interface** : `actions/executor.py::UI_HINTS` regroupe les
  raccourcis/clics, à calibrer selon la résolution et la version du jeu.
- **Provinces** : la PHASE 1 cartographie l'économie d'abord (cf. brief) ; le
  scan provincial réel reste à étendre (le mock fournit un échantillon).
