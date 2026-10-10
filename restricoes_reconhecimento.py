"""Decodificação conjunta das casas com exatamente um rei de cada cor."""
from __future__ import annotations

import numpy as np

from reconhecimento_ensemble import CLASSES, validar_probabilidades


def eleger_com_reis(probabilidades: np.ndarray, casas_vazias: tuple[int, ...] = ()) -> tuple[np.ndarray, tuple[int, ...]]:
    """Maximiza a probabilidade conjunta, proibindo reis duplicados.

    Compara a confiança no rei com a melhor alternativa não rei de cada casa.
    Escolhe casas distintas para as duas cores. A matriz original e os votos
    dos modelos permanecem intactos; probabilidades baixas continuam baixas.
    """
    matriz = validar_probabilidades(probabilidades)
    original = matriz.argmax(axis=1)
    branco, preto = CLASSES.index("K"), CLASSES.index("k")
    sem_reis = matriz.copy()
    sem_reis[:, (branco, preto)] = -1
    indices = sem_reis.argmax(axis=1)
    base = np.maximum(matriz[np.arange(64), indices], 1e-12)
    ganho_branco = np.log(np.maximum(matriz[:, branco], 1e-12)) - np.log(base)
    ganho_preto = np.log(np.maximum(matriz[:, preto], 1e-12)) - np.log(base)
    if casas_vazias:
        indices[list(casas_vazias)] = CLASSES.index("1")
        ganho_branco[list(casas_vazias)] = -np.inf
        ganho_preto[list(casas_vazias)] = -np.inf
    ganhos = ganho_branco[:, None] + ganho_preto[None, :]
    np.fill_diagonal(ganhos, -np.inf)
    if not np.isfinite(ganhos).any():
        # Um recorte sem duas casas candidatas fica inválido para revisão;
        # marcadores nunca são transformados em reis para satisfazer a regra.
        return indices, tuple(int(i) for i in np.flatnonzero(indices != original))
    casa_branca, casa_preta = np.unravel_index(np.argmax(ganhos), ganhos.shape)
    indices[casa_branca], indices[casa_preta] = branco, preto
    alteradas = tuple(int(i) for i in np.flatnonzero(indices != original))
    return indices, alteradas
