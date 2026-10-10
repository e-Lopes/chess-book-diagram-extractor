"""Identifica pontos de anotação pequenos, isolados e circulares nas casas."""
from __future__ import annotations

import cv2
import numpy as np


def casas_com_bolinhas(imagem: np.ndarray, inset: float = 0.0) -> tuple[int, ...]:
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY) if imagem.ndim == 3 else imagem
    margem = int(round(min(cinza.shape) * inset))
    recorte = cinza[margem:-margem, margem:-margem] if margem else cinza
    altura, largura = recorte.shape
    marcadores = []
    for linha in range(8):
        for coluna in range(8):
            casa = recorte[round(linha * altura / 8):round((linha + 1) * altura / 8),
                           round(coluna * largura / 8):round((coluna + 1) * largura / 8)]
            casa = cv2.resize(casa, (64, 64), interpolation=cv2.INTER_LINEAR)
            mascara = (casa < 65).astype(np.uint8) * 255
            mascara[:5] = mascara[-5:] = 0
            mascara[:, :5] = mascara[:, -5:] = 0
            # As linhas finas do fundo hachurado desaparecem; peões pretos
            # preservam corpo e base, grandes demais para serem um marcador.
            limpa = cv2.morphologyEx(mascara, cv2.MORPH_OPEN,
                                     cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
            contornos, _ = cv2.findContours(limpa, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            grandes = [c for c in contornos if cv2.contourArea(c) >= 12]
            if len(grandes) != 1:
                continue
            contorno = grandes[0]
            x, y, w, h = cv2.boundingRect(contorno)
            if not (7 <= w <= 21 and 7 <= h <= 21 and .8 <= w / h <= 1.25
                    and 23 <= x + w / 2 <= 41 and 23 <= y + h / 2 <= 41):
                continue
            area = cv2.contourArea(contorno)
            perimetro = cv2.arcLength(contorno, True)
            if perimetro <= 0 or 4 * np.pi * area / perimetro ** 2 < .72:
                continue
            # Contornos de peças brancas também devem sobreviver à verificação:
            # muito traço fora do círculo indica corpo/base, não uma bolinha.
            fora = mascara.copy()
            fora[max(0, y - 3):min(64, y + h + 3), max(0, x - 3):min(64, x + w + 3)] = 0
            # Linhas diagonais de hachura são permitidas, traços de peças não.
            horizontais = cv2.morphologyEx(fora, cv2.MORPH_OPEN, np.ones((1, 9), np.uint8))
            verticais = cv2.morphologyEx(fora, cv2.MORPH_OPEN, np.ones((9, 1), np.uint8))
            if np.count_nonzero(horizontais | verticais) > 20:
                continue
            marcadores.append((7 - linha) * 8 + coluna)
    return tuple(marcadores)
