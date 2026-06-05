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

# Calibrer une adresse sur le jeu réel par scan différentiel interactif
python -m eu5_bot.main --calibrate tresor
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
│   ├── backend.py         Interface MemoryBackend + MockMemoryBackend (module/tas/pointeurs/provinces)
│   ├── pymem_backend.py   Backend réel pymem (Windows : enum_regions, index pointeurs)
│   ├── scanner.py         Scan différentiel scalaire + signatures AOB → MemoryMap (cache JSON)
│   ├── pointers.py        PointerScanner : chaînes de pointeurs persistantes (anti-ASLR)
│   ├── provinces.py       ProvinceScanner : tableau de provinces (base/stride/count/offsets)
│   └── reader.py          GameStateReader : adresses (résolues par pointeur) → GameState
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

## Scan mémoire différentiel

Le scan est un **scan différentiel multi-passes** (technique type Cheat Engine),
seul moyen fiable d'isoler une adresse face aux milliers de candidats qu'un scan
de valeur unique renvoie sur un vrai processus :

1. `first_scan(valeur)` — toutes les adresses contenant la valeur connue.
2. La valeur évolue dans le jeu (temps qui passe, trésor qui change…).
3. `next_scan(nouvelle_valeur)` — ne garde que les candidats valant désormais la
   nouvelle valeur.
4. Répéter jusqu'à une adresse unique ; on en dérive une **signature AOB** et un
   offset relatif au module, puis on persiste dans `MemoryMap`.

- **Régions mémoire réelles** : `PymemBackend.enum_regions()` énumère via
  `VirtualQueryEx` les régions committées et lisibles ; `scan_value` (partagé)
  les parcourt par blocs avec recouvrement pour ne manquer aucune occurrence.
- **Sources des valeurs successives** :
  - hors-ligne / tests → le `MockMemoryBackend` fournit `value_provider`
    (lecture directe) et `settle` (avance du temps simulé), avec des **leurres**
    figés pour exercer réellement le différentiel ;
  - jeu réel → **calibration interactive** via `--calibrate <champ>` : on saisit
    la valeur affichée à l'écran, on laisse le jeu la faire évoluer, le scan
    converge puis enregistre l'adresse dans la carte mémoire.
- `MemorySignature` conserve les `candidates` survivants et un score de
  `confidence` (1.0 quand une seule adresse subsiste).

## Chaînes de pointeurs persistantes (anti-ASLR)

Une adresse absolue change à chaque relance du jeu (ASLR, réallocation du tas).
`memory/pointers.py::PointerScanner` effectue un **pointer scan inverse** : depuis
l'adresse cible, il remonte les pointeurs (recherche en largeur bornée par
`max_depth` / `max_offset`) jusqu'à un **pointeur statique** dans le module. La
chaîne résultante (`static_offset` + `offsets`) est stockée dans la signature et
**résolue à chaque lecture** — elle survit donc aux relances. Le `GameStateReader`
privilégie la chaîne de pointeurs et retombe sur l'adresse absolue à défaut.

Le `MockMemoryBackend` modélise un vrai graphe de pointeurs (module → tas) et
expose `relaunch()` qui rejoue l'ASLR : les tests vérifient que la lecture reste
correcte après relance via la chaîne de pointeurs.

## Scan des provinces

`memory/provinces.py::ProvinceScanner` traite le **tableau de structures** de
provinces : il localise le champ `developpement` de deux provinces (par valeur),
en déduit `base` et `stride`, sonde `count` (fin du tableau), puis détermine
l'offset de chaque champ en vérifiant sa cohérence sur une seconde province. Une
chaîne de pointeurs vers la base du tableau est recherchée pour la persistance.
Le résultat (`ProvinceLayout`) permet de lire dynamiquement toutes les provinces
(développement, slots, nombre de bâtiments).

## Notes d'implémentation & limites

- **Coordonnées d'interface** : `actions/executor.py::UI_HINTS` regroupe les
  raccourcis/clics, à calibrer selon la résolution et la version du jeu.
- **Noms de provinces** : le scan lit les champs numériques (développement,
  slots, bâtiments) ; les **chaînes de caractères** (noms réels) ne sont pas
  encore extraites, donc les provinces sont nommées « Province N ». L'exécuteur
  d'actions devra cibler les provinces par coordonnées/ID plutôt que par nom tant
  que le scan des chaînes n'est pas implémenté.
