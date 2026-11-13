"""Importa um único diagrama a partir de uma imagem avulsa ou da área de transferência.

O módulo não depende da interface: carrega JPG, PNG, GIF, BMP ou WEBP,
localiza o tabuleiro com o mesmo detector usado nos PDFs e devolve o recorte
retificado. O reconhecimento das peças continua a cargo do
``ReconhecedorForsyth``.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageOps, UnidentifiedImageError

from extrair_tabuleiros_pdf import (
    LIMIAR_ALTA_SENSIBILIDADE,
    LIMIAR_PADRAO,
    corrigir_perspectiva,
    detectar_tabuleiros,
)
from notacao_forsyth import (
    converter_idioma_para_padrao,
    converter_padrao_para_idioma,
    normalizar_posicao,
    resolver_orientacao,
    validar_posicao,
)

EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")
LADO_MINIMO_BUSCA = 640
LADO_MAXIMO_BUSCA = 2400
# Abaixo disso o recorte encontrado não ocupa a imagem de forma relevante e
# provavelmente é um ícone ou parte da página, não o diagrama colado.
FRACAO_MINIMA_AREA = 0.04
# Acima disso a imagem já é o recorte do diagrama. Usá-la inteira evita
# quadros internos deslocados; moldura e coordenadas ficam a cargo de
# ``alinhar_grade`` no reconhecedor, como nos recortes extraídos de PDFs.
FRACAO_RECORTE_JUSTO = 0.80
# Quadros mais inclinados que isso (fração do lado) são fotos em perspectiva
# e continuam sendo retificados, mesmo ocupando quase toda a imagem.
TOLERANCIA_ALINHAMENTO = 0.03


class ErroImportacaoImagem(ValueError):
    """Falha que pode ser mostrada diretamente para a pessoa usuária."""


@dataclass(frozen=True)
class TabuleiroImportado:
    imagem: np.ndarray
    quadro: np.ndarray
    confianca: float
    detectado: bool


def _para_rgb(imagem: Image.Image) -> np.ndarray:
    if imagem.mode in ("I", "I;16", "I;16B", "I;16L", "F"):
        # Cinza de 16 bits ou ponto flutuante: convert("RGB") apenas corta em
        # 255 e deixaria o diagrama quase todo branco. Reescala pela faixa real.
        valores = np.asarray(imagem, dtype=np.float64)
        minimo, maximo = float(valores.min()), float(valores.max())
        escala = 255.0 / (maximo - minimo) if maximo > minimo else 0.0
        cinza = np.clip((valores - minimo) * escala, 0, 255).astype(np.uint8)
        return np.dstack([cinza] * 3)
    if imagem.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (
            imagem.mode == "P" and "transparency" in imagem.info):
        rgba = imagem.convert("RGBA")
        alfa = np.asarray(rgba.getchannel("A"))
        if alfa.max() == 0:
            # Bitmaps de 32 bits copiados por alguns programas no Windows trazem
            # alfa zerado; compor sobre branco apagaria a imagem inteira.
            return np.asarray(rgba.convert("RGB"), dtype=np.uint8)
        fundo = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        imagem = Image.alpha_composite(fundo, rgba)
    return np.asarray(imagem.convert("RGB"), dtype=np.uint8)


def converter_pil_para_bgr(imagem: Image.Image) -> np.ndarray:
    """Converte para BGR, usando o primeiro quadro de GIFs e fundo branco na transparência."""
    try:
        imagem.seek(0)
    except (AttributeError, EOFError):
        pass
    try:
        rgb = _para_rgb(ImageOps.exif_transpose(imagem))
    except (OSError, ValueError, MemoryError) as erro:
        raise ErroImportacaoImagem("Não foi possível ler o conteúdo da imagem.") from erro
    if min(rgb.shape[:2]) < 64:
        raise ErroImportacaoImagem("A imagem é pequena demais para conter um diagrama legível.")
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def carregar_imagem(caminho: os.PathLike[str] | str) -> np.ndarray:
    caminho = Path(caminho)
    try:
        with Image.open(caminho) as imagem:
            return converter_pil_para_bgr(imagem)
    except FileNotFoundError as erro:
        raise ErroImportacaoImagem(f"Arquivo não encontrado: {caminho}") from erro
    except Image.DecompressionBombError as erro:
        raise ErroImportacaoImagem("A imagem é grande demais para ser aberta com segurança.") from erro
    except PermissionError as erro:
        raise ErroImportacaoImagem(f"Sem permissão para ler o arquivo: {caminho}") from erro
    except (UnidentifiedImageError, OSError) as erro:
        raise ErroImportacaoImagem("O arquivo não é uma imagem suportada (PNG, JPG, GIF, BMP ou WEBP).") from erro


def imagem_da_area_transferencia() -> np.ndarray | None:
    """Retorna a imagem copiada ou o primeiro arquivo de imagem copiado no Explorer."""
    try:
        conteudo = ImageGrab.grabclipboard()
    except Image.DecompressionBombError as erro:
        raise ErroImportacaoImagem("A imagem copiada é grande demais para ser aberta com segurança.") from erro
    except (OSError, NotImplementedError):
        # Área de transferência ocupada por outro programa ou formato ilegível.
        return None
    if isinstance(conteudo, Image.Image):
        return converter_pil_para_bgr(conteudo)
    if isinstance(conteudo, list):
        for item in conteudo:
            if Path(str(item)).suffix.lower() in EXTENSOES_IMAGEM:
                return carregar_imagem(item)
    return None


def _escala_de_busca(imagem: np.ndarray) -> float:
    # O detector foi calibrado para páginas a 240 DPI. Capturas pequenas de
    # sites são ampliadas para que casas e molduras tenham tamanho semelhante.
    menor = min(imagem.shape[:2])
    maior = max(imagem.shape[:2])
    if menor < LADO_MINIMO_BUSCA:
        return min(LADO_MINIMO_BUSCA / menor, LADO_MAXIMO_BUSCA / maior)
    if maior > LADO_MAXIMO_BUSCA:
        return LADO_MAXIMO_BUSCA / maior
    return 1.0


def _imagem_inteira(imagem: np.ndarray, confianca: float, detectado: bool) -> TabuleiroImportado:
    """Remove faixas uniformes externas e usa o restante, sem reamostrar, como tabuleiro."""
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    fundo = np.median(np.concatenate([cinza[0], cinza[-1], cinza[:, 0], cinza[:, -1]]))
    diferente = np.abs(cinza.astype(np.int16) - int(fundo)) > 24
    linhas = np.flatnonzero(diferente.mean(axis=1) > 0.02)
    colunas = np.flatnonzero(diferente.mean(axis=0) > 0.02)
    altura, largura = cinza.shape
    x0, x1, y0, y1 = 0, largura, 0, altura
    if len(linhas) and len(colunas):
        candidato = (int(colunas[0]), int(colunas[-1]) + 1, int(linhas[0]), int(linhas[-1]) + 1)
        if min(candidato[1] - candidato[0], candidato[3] - candidato[2]) >= min(altura, largura) * 0.5:
            x0, x1, y0, y1 = candidato
    quadro = np.array([[x0, y0], [x1 - 1, y0], [x1 - 1, y1 - 1], [x0, y1 - 1]], dtype=np.float32)
    return TabuleiroImportado(imagem[y0:y1, x0:x1].copy(), quadro, confianca, detectado)


def _alinhado_aos_eixos(quadro: np.ndarray) -> bool:
    x0, y0 = quadro.min(axis=0)
    x1, y1 = quadro.max(axis=0)
    cantos = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)
    tolerancia = max(2.0, TOLERANCIA_ALINHAMENTO * float(min(x1 - x0, y1 - y0)))
    return all(float(np.min(np.linalg.norm(cantos - ponto, axis=1))) <= tolerancia for ponto in quadro)


def localizar_tabuleiro(imagem: np.ndarray) -> TabuleiroImportado:
    """Escolhe o maior tabuleiro plausível; sem detecção, usa a imagem inteira."""
    if not isinstance(imagem, np.ndarray) or imagem.dtype != np.uint8 or imagem.ndim != 3:
        raise ErroImportacaoImagem("Imagem inválida.")
    escala = _escala_de_busca(imagem)
    busca = imagem if escala == 1.0 else cv2.resize(
        imagem, None, fx=escala, fy=escala,
        interpolation=cv2.INTER_CUBIC if escala > 1 else cv2.INTER_AREA)
    area_total = float(busca.shape[0] * busca.shape[1])
    for limiar, sensivel in ((LIMIAR_PADRAO, False), (LIMIAR_ALTA_SENSIBILIDADE, True)):
        candidatos = [
            c for c in detectar_tabuleiros(busca, limiar=limiar, alta_sensibilidade=sensivel)
            if cv2.contourArea(c.quadro) >= area_total * FRACAO_MINIMA_AREA
        ]
        if candidatos:
            # Em capturas com miniaturas ao lado, o diagrama principal é o maior.
            melhor = max(candidatos, key=lambda c: cv2.contourArea(c.quadro) * (0.5 + c.confianca))
            if (cv2.contourArea(melhor.quadro) >= area_total * FRACAO_RECORTE_JUSTO
                    and _alinhado_aos_eixos(melhor.quadro)):
                return _imagem_inteira(imagem, melhor.confianca, True)
            quadro = (melhor.quadro / escala).astype(np.float32)
            return TabuleiroImportado(corrigir_perspectiva(imagem, quadro), quadro, melhor.confianca, True)
    return _imagem_inteira(imagem, 0.0, False)


def fen_completa(posicao: str, lado: str, idioma: str) -> str:
    """FEN padrão (letras inglesas) com lado a jogar, pronta para outros programas."""
    padrao = converter_idioma_para_padrao(posicao, idioma)
    return f"{padrao} {'b' if lado == 'b' else 'w'} - - 0 1"


def interpretar_posicao(texto: str, idioma: str) -> tuple[str | None, str | None]:
    """Lê o que foi digitado ou colado no campo de posição.

    Aceita só a disposição das peças, a disposição seguida de ``w``/``b`` ou
    uma FEN completa. Uma FEN em letras inglesas colada com a notação
    portuguesa ativa (ou vice-versa) é convertida quando só faz sentido no
    outro alfabeto. Retorna a posição no ``idioma`` e o lado, se informado.
    """
    campos = texto.split()
    if not campos:
        return None, None
    lado = campos[1].lower() if len(campos) > 1 and campos[1].lower() in ("w", "b") else None
    disposicao = campos[0]
    if validar_posicao(disposicao, idioma)[0]:
        return normalizar_posicao(disposicao, idioma), lado
    outro = "en" if idioma == "pt" else "pt"
    if validar_posicao(disposicao, outro)[0]:
        padrao = converter_idioma_para_padrao(disposicao, outro)
        return converter_padrao_para_idioma(padrao, idioma), lado
    return None, lado


def parece_invertido(posicao: str, idioma: str) -> bool:
    """Indica, pelos peões, um diagrama desenhado com as pretas embaixo."""
    try:
        _posicao, girado, ambiguo = resolver_orientacao(converter_idioma_para_padrao(posicao, idioma))
    except ValueError:
        return False
    return girado and not ambiguo
