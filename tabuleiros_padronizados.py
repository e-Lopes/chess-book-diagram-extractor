"""Desenha posições Forsyth e padroniza diagramas sobre o PDF original.

As peças vetoriais são do conjunto clássico Cburnett (BSD-3-Clause). A sobreposição opaca
fica restrita ao quadrilátero de cada diagrama; as páginas não são rasterizadas.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from functools import lru_cache
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import cv2
import fitz
import numpy as np

from extrair_tabuleiros_pdf import ErroExtracao, _verificar_cancelamento
from notacao_forsyth import converter_idioma_para_padrao, expandir_posicao, PECAS_PADRAO, separar_posicao_lado, caminho_recurso


@lru_cache(maxsize=12)
def _svg_peca(peca: str) -> str:
    nome = ("w" if peca.isupper() else "b") + peca.upper() + ".svg"
    caminho = caminho_recurso("assets", "pieces", "cburnett", nome)
    raiz = ET.fromstring(caminho.read_bytes())
    raiz.set("viewBox", raiz.get("viewBox", "0 0 45 45"))
    raiz.set("width", "100")
    raiz.set("height", "100")
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    return ET.tostring(raiz, encoding="unicode")


def gerar_svg_tabuleiro(posicao: str, idioma: str = "pt") -> str:
    campos = posicao.strip().split()
    if len(campos) == 6 and campos[1] in ("w", "b"):
        posicao = campos[0]  # A imagem também aceita uma FEN completa.
    posicao, _lado = separar_posicao_lado(posicao)
    tabuleiro = expandir_posicao(converter_idioma_para_padrao(posicao, idioma), PECAS_PADRAO)
    partes = ['<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="0 0 800 800">']
    for linha, casas in enumerate(tabuleiro):
        for coluna, peca in enumerate(casas):
            x, y = coluna * 100, linha * 100
            fundo = "#ffffff" if (linha + coluna) % 2 == 0 else "#c9c9c9"
            partes.append(f'<rect x="{x}" y="{y}" width="100" height="100" fill="{fundo}"/>')
            if peca:
                partes.append(f'<g transform="translate({x},{y})">{_svg_peca(peca)}</g>')
    partes.append('<rect x="1" y="1" width="798" height="798" fill="none" stroke="#161616" stroke-width="2"/></svg>')
    return "".join(partes)


def renderizar_tabuleiro(posicao: str, idioma: str = "pt", tamanho: int = 800) -> np.ndarray:
    if not isinstance(tamanho, int) or not 64 <= tamanho <= 4096:
        raise ValueError("O tamanho do tabuleiro deve estar entre 64 e 4096 pixels.")
    svg = gerar_svg_tabuleiro(posicao, idioma).encode()
    with fitz.open(stream=svg, filetype="svg") as documento:
        pix = documento[0].get_pixmap(matrix=fitz.Matrix(tamanho / 800, tamanho / 800),
                                     colorspace=fitz.csRGB, alpha=False)
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


@lru_cache(maxsize=26)
def _imagem_casa(peca: str, paridade: int) -> np.ndarray:
    fundo = "#ffffff" if paridade == 0 else "#c9c9c9"
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
           f'<rect width="100" height="100" fill="{fundo}"/>'
           f'{_svg_peca(peca) if peca else ""}</svg>')
    with fitz.open(stream=svg.encode(), filetype="svg") as documento:
        pix = documento[0].get_pixmap(colorspace=fitz.csRGB, alpha=False)
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(100, 100, 3)
        imagem = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        imagem.setflags(write=False)
        return imagem


def renderizar_previa(posicao: str, idioma: str = "pt") -> np.ndarray:
    """Monta a prévia com casas reutilizáveis; a exportação mantém o SVG completo."""
    campos = posicao.strip().split()
    if len(campos) == 6 and campos[1] in ("w", "b"):
        posicao = campos[0]
    posicao, _lado = separar_posicao_lado(posicao)
    casas = expandir_posicao(converter_idioma_para_padrao(posicao, idioma), PECAS_PADRAO)
    imagem = np.empty((800, 800, 3), np.uint8)
    for linha, pecas in enumerate(casas):
        for coluna, peca in enumerate(pecas):
            imagem[linha * 100:(linha + 1) * 100, coluna * 100:(coluna + 1) * 100] = (
                _imagem_casa(peca, (linha + coluna) % 2))
    cv2.rectangle(imagem, (1, 1), (798, 798), (22, 22, 22), thickness=2)
    return imagem


@dataclass(frozen=True)
class DiagramaPadronizado:
    pagina: int
    quadro_pdf: tuple[tuple[float, float], ...]
    posicao: str


def localizar_diagramas_antigos(origem, candidatos, *, progresso=None, cancelado=None):
    """Recupera cantos por correspondência visual, sem presumir ordem ou quantidade.

    Recortes semelhantes demais na mesma página são omitidos: não há informação
    suficiente para atribuir uma posição editada a um deles com segurança.
    """
    from extrair_tabuleiros_pdf import (
        DPI_PADRAO, _quadros_de_imagens_pdf, detectar_tabuleiros, renderizar_pagina,
    )
    localizacoes = {}
    paginas = sorted({c.pagina for c in candidatos})
    with fitz.open(origem) as documento:
        for atual, numero in enumerate(paginas, 1):
            _verificar_cancelamento(cancelado)
            if not 1 <= numero <= len(documento):
                continue
            pagina = documento[numero - 1]
            imagem = renderizar_pagina(pagina, DPI_PADRAO)
            encontrados = detectar_tabuleiros(imagem, numero,
                quadros_adicionais=_quadros_de_imagens_pdf(pagina, DPI_PADRAO))
            referencias = [(i, c) for i, c in enumerate(candidatos) if c.pagina == numero]
            def assinatura(recorte):
                cinza = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY) if recorte.ndim == 3 else recorte
                return cv2.resize(cinza, (96, 96), interpolation=cv2.INTER_AREA).astype(np.float32)
            assinaturas = [assinatura(c.imagem) for c in encontrados]
            propostas = []
            for indice, candidato in referencias:
                referencia = assinatura(candidato.imagem)
                pontuacoes = [float(cv2.matchTemplate(a, referencia, cv2.TM_CCOEFF_NORMED)[0, 0])
                             for a in assinaturas]
                ordem = sorted(range(len(pontuacoes)), key=pontuacoes.__getitem__, reverse=True)
                if not ordem or pontuacoes[ordem[0]] < 0.92:
                    continue
                if len(ordem) > 1 and pontuacoes[ordem[0]] - pontuacoes[ordem[1]] < 0.04:
                    continue
                propostas.append((indice, ordem[0]))
            for indice, eleito in propostas:
                if sum(j == eleito for _, j in propostas) == 1:
                    localizacoes[indice] = tuple(tuple(float(v) for v in ponto)
                        for ponto in encontrados[eleito].quadro * (72 / DPI_PADRAO))
            if progresso:
                progresso(atual, len(paginas))
    return localizacoes


def _validar_quadro(quadro_pdf: Sequence[Sequence[float]], pagina: fitz.Page) -> np.ndarray:
    quadro = np.asarray(quadro_pdf, np.float32)
    if quadro.shape != (4, 2) or not np.isfinite(quadro).all():
        raise ValueError("O diagrama precisa de quatro cantos válidos no PDF original.")
    if not cv2.isContourConvex(quadro) or cv2.contourArea(quadro) < 1:
        raise ValueError("O quadro do diagrama não é um quadrilátero convexo.")
    if ((quadro < -1).any() or (quadro[:, 0] > pagina.rect.width + 1).any()
            or (quadro[:, 1] > pagina.rect.height + 1).any()):
        raise ValueError("O diagrama ultrapassa os limites da página original.")
    # Mantém a correspondência a8/h8/h1/a1; reordenar após derrotacionar
    # trocaria a orientação de páginas com rotação 90, 180 ou 270 graus.
    return np.array([tuple(fitz.Point(*p) * pagina.derotation_matrix) for p in quadro], np.float32)


def exportar_pdf_padronizado(
    origem: os.PathLike[str] | str,
    destino: os.PathLike[str] | str,
    diagramas: Sequence[DiagramaPadronizado],
    *,
    idioma: str = "pt",
    progresso: Callable[[int, int], None] | None = None,
    cancelado: Callable[[], bool] | None = None,
) -> Path:
    fonte, saida = Path(origem).resolve(), Path(destino).expanduser().resolve()
    if saida.suffix.lower() != ".pdf":
        saida = saida.with_suffix(".pdf")
    if fonte == saida:
        raise ValueError("Escolha outro nome para a cópia padronizada do livro.")
    if not diagramas:
        raise ValueError("Nenhum diagrama com posição e localização válidas para padronizar.")
    saida.parent.mkdir(parents=True, exist_ok=True)
    temporario = None
    with fitz.open(fonte) as documento:
        if not documento.is_pdf or documento.needs_pass:
            raise ErroExtracao("O livro deve ser um PDF acessível, sem senha.")
        # Valida tudo antes de desenhar ou criar a saída.
        preparados = []
        for diagrama in diagramas:
            _verificar_cancelamento(cancelado)
            if not 1 <= diagrama.pagina <= len(documento):
                raise ValueError("A página do diagrama não existe no livro original.")
            pagina = documento[diagrama.pagina - 1]
            quadro = _validar_quadro(diagrama.quadro_pdf, pagina)
            gerar_svg_tabuleiro(diagrama.posicao, idioma)
            preparados.append((diagrama, quadro))
        cache_imagens: dict[str, np.ndarray] = {}
        for indice, (diagrama, quadro) in enumerate(preparados, 1):
            _verificar_cancelamento(cancelado)
            imagem = cache_imagens.get(diagrama.posicao)
            if imagem is None:
                imagem = renderizar_tabuleiro(diagrama.posicao, idioma)
                if len(cache_imagens) >= 8:
                    cache_imagens.clear()
                cache_imagens[diagrama.posicao] = imagem
            minimo, maximo = quadro.min(axis=0), quadro.max(axis=0)
            # Até 144 DPI na sobreposição. O recorte é feito no próprio PDF.
            escala = min(2.0, 1600 / max(maximo - minimo))
            largura, altura = np.maximum(2, np.ceil((maximo - minimo) * escala).astype(int))
            # Os últimos cantos precisam cair no último pixel, para que a
            # borda direita/inferior não seja cortada pelo raster de destino.
            alvo = (quadro - minimo) * np.array([(largura - 1) / (maximo[0] - minimo[0]),
                                                (altura - 1) / (maximo[1] - minimo[1])])
            tamanho = imagem.shape[0]
            pontos = np.array([[0, 0], [tamanho - 1, 0], [tamanho - 1, tamanho - 1], [0, tamanho - 1]], np.float32)
            matriz = cv2.getPerspectiveTransform(pontos, alvo.astype(np.float32))
            sobreposicao = cv2.warpPerspective(imagem, matriz, (int(largura), int(altura)),
                flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            sucesso, buffer = cv2.imencode(".png", sobreposicao)
            if not sucesso:
                raise ErroExtracao("Não foi possível gerar um diagrama padronizado.")
            pagina = documento[diagrama.pagina - 1]
            pagina.insert_image(fitz.Rect(*minimo, *maximo),
                stream=buffer.tobytes(), keep_proportion=False, overlay=True)
            # Um PNG com alpha ativa a composição de transparência da página
            # inteira e muda levemente até o antialias do texto externo. Usamos
            # imagem opaca + clipping vetorial só no novo stream de conteúdo.
            cantos_pdf = [fitz.Point(*p) * ~pagina.transformation_matrix for p in quadro]
            caminho = "\n".join(f"{p.x:.6f} {p.y:.6f} {'m' if i == 0 else 'l'}"
                                for i, p in enumerate(cantos_pdf))
            xref = pagina.get_contents()[-1]
            conteudo = documento.xref_stream(xref)
            documento.update_stream(xref, f"q\n{caminho}\nh W n\n".encode() + conteudo + b"\nQ\n")
            if progresso is not None:
                progresso(indice, len(preparados))
        _verificar_cancelamento(cancelado)
        descritor, temporario = tempfile.mkstemp(prefix="livro_padronizado_", suffix=".pdf", dir=saida.parent)
        os.close(descritor)
        try:
            documento.save(temporario, garbage=4, deflate=True)
            _verificar_cancelamento(cancelado)
            os.replace(temporario, saida)
        finally:
            if temporario and os.path.exists(temporario):
                os.unlink(temporario)
    return saida
