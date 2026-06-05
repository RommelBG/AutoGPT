"""Recherche de chaînes de pointeurs persistantes (pointer scan inverse).

Une adresse absolue change à chaque relance du jeu (ASLR, réallocation du tas).
Pour relire une valeur de façon fiable d'une session à l'autre, on cherche un
**pointeur statique** dans le module qui mène, par déréférencements successifs,
à la valeur cible :

    adresse_valeur = (((module_base + static_offset)*) + off1)* ... + off_n

L'algorithme part de l'adresse cible et remonte les pointeurs : à chaque niveau,
on cherche toute adresse ``P`` contenant un pointeur vers ``cible - o`` (offset
``o`` petit). Si ``P`` est dans le module, la chaîne est trouvée ; sinon ``P``
devient la nouvelle cible (un cran plus profond), borné par ``max_depth`` et
``max_offset``.
"""

from __future__ import annotations

from collections import deque

from ..models import PointerChain
from .backend import MemoryBackend


class PointerScanner:
    """Trouve une chaîne de pointeurs statique menant à une adresse cible."""

    def __init__(
        self,
        backend: MemoryBackend,
        max_depth: int = 4,
        max_offset: int = 0x600,
        alignment: int = 8,
        index: dict[int, list[int]] | None = None,
    ) -> None:
        self.backend = backend
        self.max_depth = max_depth
        self.max_offset = max_offset
        self.alignment = alignment
        self._index = index  # index pré-construit réutilisable (perf)

    def index(self) -> dict[int, list[int]]:
        """Index ``valeur_pointée -> [adresses]`` (construit puis mis en cache)."""
        if self._index is None:
            self._index = self.backend.build_pointer_index(self.alignment)
        return self._index

    def scan(self, target_address: int) -> PointerChain | None:
        """Renvoie une ``PointerChain`` vers ``target_address``, ou None."""
        module_base, module_size = self.backend.module_range()
        if module_size <= 0:
            return None
        index = self.index()

        # File BFS : (adresse_courante, offsets_accumulés, profondeur)
        queue: deque[tuple[int, list[int], int]] = deque([(target_address, [], 0)])
        visited: set[int] = {target_address}

        while queue:
            addr, offsets, depth = queue.popleft()
            for o in range(0, self.max_offset + 1):
                holders = index.get(addr - o)
                if not holders:
                    continue
                new_offsets = [o] + offsets
                for holder in holders:
                    if module_base <= holder < module_base + module_size:
                        # Pointeur statique atteint : chaîne complète.
                        return PointerChain(
                            static_offset=holder - module_base, offsets=new_offsets
                        )
                    if depth + 1 < self.max_depth and holder not in visited:
                        visited.add(holder)
                        queue.append((holder, new_offsets, depth + 1))
        return None

    def verify(self, chain: PointerChain, expected_address: int) -> bool:
        """Vérifie qu'une chaîne se résout bien vers l'adresse attendue."""
        resolved = self.backend.resolve_chain(self.backend.module_base(), chain)
        return resolved == expected_address
