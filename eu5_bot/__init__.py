"""Bot Autonome EU5 — lit l'état d'Europa Universalis V en mémoire, le soumet à
un Conseil multi-agents LLM, puis exécute la décision dans le jeu.

Modules principaux :
    - ``config``   : configuration centrale (clés API, modèles, options).
    - ``models``   : structures de données partagées (état du jeu, carte mémoire,
                     réponses des conseillers, décision du coordinateur).
    - ``memory``   : scan et lecture de la mémoire du processus EU5.
    - ``council``  : le Conseil LLM (4 conseillers + coordinateur).
    - ``actions``  : exécution des décisions dans le jeu.
    - ``ui``       : interface desktop tkinter.
    - ``bot``      : boucle de contrôle reliant le tout.
"""

__version__ = "0.1.0"
