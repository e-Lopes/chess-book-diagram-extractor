"""Localiza a grade interna sem recortar por uma margem fixa simétrica."""
from __future__ import annotations

import cv2
import numpy as np


def _limites_eixo(perfil: np.ndarray) -> tuple[int, int]:
    # Sete transições regularmente espaçadas devem aparecer dentro da grade.
    # Procura margens independentes: letras apenas à esquerda e embaixo são
    # comuns. A preferência por menos recorte resolve empates de antialias.
    perfil = cv2.GaussianBlur(perfil.reshape(1, -1), (3, 1), 0).ravel()
    inicios, finais = np.meshgrid(np.arange(0, 46), np.arange(274, 321), indexing="ij")
    pontos = np.rint(inicios[..., None] + (finais - inicios)[..., None] * np.arange(1, 8) / 8).astype(int) - 1
    evidencias = perfil[np.clip(pontos, 0, len(perfil) - 1)]
    scores = evidencias.mean(axis=2) + .3 * np.median(evidencias, axis=2)
    scores -= .025 * (inicios + 320 - finais)
    i, j = np.unravel_index(np.argmax(scores), scores.shape)
    inicio, fim = int(inicios[i, j]), int(finais[i, j])
    if max(inicio, 320 - fim) < 15:
        # Pequenas diferenças de fase surgem em casas hachuradas e peças nas
        # extremidades. Só remove uma faixa externa de tamanho significativo.
        return 0, 320
    if abs(inicio - (320 - fim)) < 6 and max(inicio, 320 - fim) <= 16:
        # Molduras pequenas simétricas já fazem parte da busca de inset do
        # reconhecedor. Não soma dois recuos, que cortariam bases das peças.
        return 0, 320
    base = perfil[np.rint(np.arange(1, 8) * 40).astype(int) - 1]
    score_base = float(base.mean() + .3 * np.median(base))
    if (scores[i, j] < score_base * 1.35 + 2
            or np.count_nonzero(evidencias[i, j] >= 4) < 6):
        return 0, 320
    return inicio, fim


def alinhar_grade(imagem: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Retorna a imagem das 64 casas e seus limites no recorte original.

    Na ausência de sete transições fortes por eixo mantém o recorte. Não
    altera os pixels originais nem as coordenadas PDF usadas na exportação.
    """
    if (not isinstance(imagem, np.ndarray) or imagem.dtype != np.uint8
            or imagem.ndim not in (2, 3) or min(imagem.shape[:2]) < 8
            or (imagem.ndim == 3 and imagem.shape[2] not in (3, 4))):
        raise ValueError("Imagem inválida para reconhecimento.")
    altura, largura = imagem.shape[:2]
    rgb = cv2.resize(imagem, (320, 320), interpolation=cv2.INTER_AREA).astype(np.float32)
    if rgb.ndim == 2:
        rgb = rgb[..., None]
    dx = np.median(np.max(np.abs(np.diff(rgb[16:304], axis=1)), axis=2), axis=0)
    dy = np.median(np.max(np.abs(np.diff(rgb[:, 16:304], axis=0)), axis=2), axis=1)
    x0, x1 = _limites_eixo(dx)
    y0, y1 = _limites_eixo(dy)
    limites = (round(x0 * largura / 320), round(y0 * altura / 320),
               round(x1 * largura / 320), round(y1 * altura / 320))
    a, b, c, d = limites
    return imagem[b:d, a:c], limites
