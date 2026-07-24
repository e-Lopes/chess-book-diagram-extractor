"""Extrai diagramas de tabuleiro de um livro PDF.

O programa renderiza cada pagina, procura quadrilateros com estrutura visual de
um tabuleiro 8x8 e cria um novo PDF A4 com um tabuleiro por pagina.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import cv2
import fitz
import numpy as np


DPI_PADRAO = 240
LIMIAR_PADRAO = 0.24
TAMANHO_A4 = fitz.paper_size("a4")


class ErroExtracao(RuntimeError):
    """Erro que pode ser apresentado diretamente para a pessoa usuaria."""


@dataclass
class Candidato:
    pagina: int
    quadro: np.ndarray
    imagem: np.ndarray
    confianca: float

    @property
    def x(self) -> float:
        return float(np.min(self.quadro[:, 0]))

    @property
    def y(self) -> float:
        return float(np.min(self.quadro[:, 1]))


@dataclass(frozen=True)
class ResultadoExtracao:
    paginas_processadas: int
    diagramas_encontrados: int
    arquivo_saida: Path | None


def _ordenar_pontos(pontos: np.ndarray) -> np.ndarray:
    pontos = np.asarray(pontos, dtype=np.float32).reshape(4, 2)
    soma = pontos.sum(axis=1)
    diferenca = np.diff(pontos, axis=1).ravel()
    return np.array(
        [
            pontos[np.argmin(soma)],
            pontos[np.argmin(diferenca)],
            pontos[np.argmax(soma)],
            pontos[np.argmax(diferenca)],
        ],
        dtype=np.float32,
    )


def _lado_do_quadro(quadro: np.ndarray) -> int:
    q = _ordenar_pontos(quadro)
    lados = [
        np.linalg.norm(q[1] - q[0]),
        np.linalg.norm(q[2] - q[1]),
        np.linalg.norm(q[3] - q[2]),
        np.linalg.norm(q[0] - q[3]),
    ]
    return max(96, int(round(max(lados))))


def corrigir_perspectiva(imagem: np.ndarray, quadro: np.ndarray) -> np.ndarray:
    """Transforma um quadrilatero detectado em uma imagem quadrada."""
    origem = _ordenar_pontos(quadro)
    lado = _lado_do_quadro(origem)
    destino = np.array(
        [[0, 0], [lado - 1, 0], [lado - 1, lado - 1], [0, lado - 1]],
        dtype=np.float32,
    )
    matriz = cv2.getPerspectiveTransform(origem, destino)
    return cv2.warpPerspective(
        imagem,
        matriz,
        (lado, lado),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _medias_casas(cinza: np.ndarray) -> np.ndarray:
    normalizada = cv2.resize(cinza, (320, 320), interpolation=cv2.INTER_AREA)
    medias = np.zeros((8, 8), dtype=np.float32)
    # Usa uma regiao ampla, mas evita as linhas/bordas entre casas.
    margem = 6
    for linha in range(8):
        for coluna in range(8):
            y0, x0 = linha * 40 + margem, coluna * 40 + margem
            casa = normalizada[y0 : (linha + 1) * 40 - margem, x0 : (coluna + 1) * 40 - margem]
            # A mediana sofre menos com o desenho das pecas que a media.
            medias[linha, coluna] = float(np.median(casa))
    return medias


def _evidencia_grade_8x8(cinza: np.ndarray) -> tuple[float, float, float]:
    """Mede correlacao, contraste e consistencia de uma grade xadrez 8x8.

    O percentil 30 representa o fundo da casa: desenhos pequenos e letras nao
    ocupam pixels suficientes para altera-lo, enquanto casas pintadas ou
    pontilhadas alteram toda a regiao. Alguns insets compensam a moldura.
    """
    base = cv2.resize(cinza, (360, 360), interpolation=cv2.INTER_AREA)
    paridade = np.fromfunction(lambda y, x: (x + y) % 2, (8, 8), dtype=int).astype(bool)
    ideal = np.where(paridade, 1.0, -1.0).astype(np.float32)
    melhor = (0.0, 0.0, 0.0)

    for inset in (0, 5, 9, 13, 17):
        area = base[inset : 360 - inset, inset : 360 - inset] if inset else base
        normalizada = cv2.resize(area, (320, 320), interpolation=cv2.INTER_AREA)
        assinatura = np.zeros((8, 8), dtype=np.float32)
        for linha in range(8):
            for coluna in range(8):
                y0, x0 = linha * 40 + 6, coluna * 40 + 6
                casa = normalizada[y0 : (linha + 1) * 40 - 6, x0 : (coluna + 1) * 40 - 6]
                assinatura[linha, coluna] = float(np.percentile(casa, 30))

        mediana_a = float(np.median(assinatura[paridade]))
        mediana_b = float(np.median(assinatura[~paridade]))
        contraste = abs(mediana_a - mediana_b) / 255.0
        centrada = assinatura - float(np.mean(assinatura))
        denominador = float(np.linalg.norm(centrada) * np.linalg.norm(ideal))
        correlacao = abs(float(np.sum(centrada * ideal)) / denominador) if denominador else 0.0

        escura = paridade if mediana_a < mediana_b else ~paridade
        corretas = 0
        comparacoes = 0
        for linha in range(8):
            for coluna in range(8):
                for dl, dc in ((0, 1), (1, 0)):
                    viz_linha, viz_coluna = linha + dl, coluna + dc
                    if viz_linha >= 8 or viz_coluna >= 8:
                        continue
                    atual = assinatura[linha, coluna]
                    vizinha = assinatura[viz_linha, viz_coluna]
                    diferenca = vizinha - atual if escura[linha, coluna] else atual - vizinha
                    corretas += int(diferenca >= 3.0)
                    comparacoes += 1
        consistencia = corretas / comparacoes if comparacoes else 0.0
        if (0.55 * correlacao + 0.20 * min(1.0, contraste / 0.16) + 0.25 * consistencia) > (
            0.55 * melhor[0] + 0.20 * min(1.0, melhor[1] / 0.16) + 0.25 * melhor[2]
        ):
            melhor = (correlacao, contraste, consistencia)
    return melhor


def _continuidade_bordas(cinza: np.ndarray) -> float:
    """Mede se existem linhas continuas nos quatro lados do quadrado."""
    normalizada = cv2.resize(cinza, (320, 320), interpolation=cv2.INTER_AREA)
    _, tinta = cv2.threshold(normalizada, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    tinta = tinta.astype(np.float32) / 255.0
    faixa = 18
    lados = [
        float(np.max(np.mean(tinta[:faixa, :], axis=1))),
        float(np.max(np.mean(tinta[-faixa:, :], axis=1))),
        float(np.max(np.mean(tinta[:, :faixa], axis=0))),
        float(np.max(np.mean(tinta[:, -faixa:], axis=0))),
    ]
    # O menor lado evita que duas linhas verticais isoladas sejam confundidas
    # com a moldura completa de um tabuleiro.
    return min(lados)


def _cobertura_casas_escuras(cinza: np.ndarray) -> float:
    """Mede preenchimento de fundo, diferenciando casas de glifos esparsos."""
    normalizada = cv2.resize(cinza, (320, 320), interpolation=cv2.INTER_AREA)
    _, tinta = cv2.threshold(normalizada, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coberturas = np.zeros((8, 8), dtype=np.float32)
    margem = 5
    for linha in range(8):
        for coluna in range(8):
            y0, x0 = linha * 40 + margem, coluna * 40 + margem
            casa = tinta[y0 : (linha + 1) * 40 - margem, x0 : (coluna + 1) * 40 - margem]
            coberturas[linha, coluna] = float(np.mean(casa > 0))
    paridade = np.fromfunction(lambda y, x: (x + y) % 2, (8, 8), dtype=int).astype(bool)
    # Em um tabuleiro, uma das paridades tem fundo pintado ou pontilhado em
    # muitas casas. Letras em uma folha branca ocupam apenas pequenas ilhas.
    return max(float(np.median(coberturas[paridade])), float(np.median(coberturas[~paridade])))


def pontuar_tabuleiro(recorte: np.ndarray) -> float:
    """Retorna uma confianca entre 0 e 1 para a estrutura de tabuleiro 8x8."""
    if recorte.size == 0 or min(recorte.shape[:2]) < 64:
        return 0.0
    cinza_original = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY) if recorte.ndim == 3 else recorte
    cinza_original = cv2.resize(cinza_original, (320, 320), interpolation=cv2.INTER_AREA)
    correlacao, contraste, consistencia = _evidencia_grade_8x8(cinza_original)

    # A alternancia bidimensional e obrigatoria. Molduras, fotografias de uma
    # peca e tabelas de texto nao podem compensar a ausencia desta estrutura.
    if correlacao < 0.34 or contraste < 0.028 or consistencia < 0.62:
        return 0.0

    cinza = cv2.equalizeHist(cinza_original)

    # Bordas externas escuras sao comuns nos diagramas impressos e ajudam a
    # rejeitar fotografias ou blocos de texto, mas nao sao obrigatorias.
    espessura = max(2, cinza.shape[0] // 80)
    borda = np.concatenate(
        [
            cinza[:espessura, :].ravel(),
            cinza[-espessura:, :].ravel(),
            cinza[:, :espessura].ravel(),
            cinza[:, -espessura:].ravel(),
        ]
    )
    interior = cinza[espessura * 3 : -espessura * 3, espessura * 3 : -espessura * 3]
    bonus_borda = np.clip((float(np.mean(interior)) - float(np.mean(borda))) / 100.0, 0.0, 1.0)

    continuidade = _continuidade_bordas(cinza)
    cobertura = _cobertura_casas_escuras(cinza)
    # Uma moldura completa OU casas realmente preenchidas e obrigatoria. Isso
    # rejeita tabelas 8x8 de texto, mesmo quando o negrito alterna por paridade.
    if continuidade < 0.32 and cobertura < 0.20:
        return 0.0

    # O contraste recebe limite para que livros com casas apenas pontilhadas
    # ainda sejam aceitos. A correlacao preserva a alternancia das 64 casas.
    score = (
        0.48 * correlacao
        + 0.20 * min(1.0, contraste / 0.16)
        + 0.17 * consistencia
        + 0.06 * bonus_borda
        + 0.05 * min(1.0, continuidade / 0.70)
        + 0.04 * min(1.0, cobertura / 0.45)
    )
    return float(np.clip(score, 0.0, 1.0))


def _mascaras_de_busca(cinza: np.ndarray) -> Iterable[np.ndarray]:
    borrada = cv2.GaussianBlur(cinza, (5, 5), 0)
    yield cv2.Canny(borrada, 45, 140)
    yield cv2.adaptiveThreshold(
        borrada,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        41,
        11,
    )


def _quadros_candidatos(imagem: np.ndarray) -> list[np.ndarray]:
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    menor_dimensao = min(cinza.shape)
    lado_minimo = max(70, int(menor_dimensao * 0.105))
    lado_maximo = int(menor_dimensao * 0.82)
    quadros: list[np.ndarray] = []

    for mascara in _mascaras_de_busca(cinza):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        fechada = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, kernel, iterations=2)
        contornos, _ = cv2.findContours(fechada, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contorno in contornos:
            perimetro = cv2.arcLength(contorno, True)
            if perimetro <= 0:
                continue
            aproximado = cv2.approxPolyDP(contorno, 0.025 * perimetro, True)
            if len(aproximado) == 4 and cv2.isContourConvex(aproximado):
                quadro = aproximado.reshape(4, 2).astype(np.float32)
            else:
                retangulo = cv2.minAreaRect(contorno)
                quadro = cv2.boxPoints(retangulo).astype(np.float32)

            q = _ordenar_pontos(quadro)
            larguras = [np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3])]
            alturas = [np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1])]
            largura, altura = float(np.mean(larguras)), float(np.mean(alturas))
            if min(largura, altura) < lado_minimo or max(largura, altura) > lado_maximo:
                continue
            if max(largura, altura) / max(1.0, min(largura, altura)) > 1.18:
                continue
            if cv2.contourArea(q.astype(np.float32)) < lado_minimo**2 * 0.7:
                continue
            quadros.append(q)
    return quadros


def _caixa(quadro: np.ndarray) -> tuple[float, float, float, float]:
    return (
        float(np.min(quadro[:, 0])),
        float(np.min(quadro[:, 1])),
        float(np.max(quadro[:, 0])),
        float(np.max(quadro[:, 1])),
    )


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    ax1, ay1, ax2, ay2 = _caixa(a)
    bx1, by1, bx2, by2 = _caixa(b)
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    uniao = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / uniao if uniao > 0 else 0.0


def _sobreposicao_menor(a: np.ndarray, b: np.ndarray) -> float:
    """Fracao da menor caixa coberta; identifica contornos aninhados."""
    ax1, ay1, ax2, ay2 = _caixa(a)
    bx1, by1, bx2, by2 = _caixa(b)
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    menor_area = min((ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1))
    return inter / menor_area if menor_area > 0 else 0.0


def remover_duplicados(candidatos: Sequence[Candidato], limite_iou: float = 0.55) -> list[Candidato]:
    mantidos: list[Candidato] = []
    for candidato in sorted(candidatos, key=lambda item: item.confianca, reverse=True):
        if all(
            _iou(candidato.quadro, existente.quadro) < limite_iou
            and _sobreposicao_menor(candidato.quadro, existente.quadro) < 0.78
            for existente in mantidos
        ):
            mantidos.append(candidato)
    return sorted(mantidos, key=lambda item: (item.pagina, item.y, item.x))


def detectar_tabuleiros(imagem: np.ndarray, pagina: int = 1, limiar: float = LIMIAR_PADRAO) -> list[Candidato]:
    encontrados: list[Candidato] = []
    for quadro in _quadros_candidatos(imagem):
        recorte = corrigir_perspectiva(imagem, quadro)
        confianca = pontuar_tabuleiro(recorte)
        if confianca >= limiar:
            encontrados.append(Candidato(pagina, quadro, recorte, confianca))
    return remover_duplicados(encontrados)


def renderizar_pagina(pagina: fitz.Page, dpi: int = DPI_PADRAO) -> np.ndarray:
    pixmap = pagina.get_pixmap(dpi=dpi, alpha=False, colorspace=fitz.csRGB)
    matriz = np.frombuffer(pixmap.samples, dtype=np.uint8)
    rgb = matriz.reshape(pixmap.height, pixmap.width, pixmap.n)[..., :3]
    # OpenCV trabalha em BGR. A conversao evita trocar vermelho e azul no PDF
    # final caso o livro tenha tabuleiros coloridos.
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def detectar_no_pdf(
    caminho_pdf: os.PathLike[str] | str,
    dpi: int = DPI_PADRAO,
    progresso: Callable[[int, int, int], None] | None = None,
) -> tuple[int, list[Candidato]]:
    caminho = Path(caminho_pdf)
    if not caminho.is_file():
        raise ErroExtracao(f"Arquivo nao encontrado: {caminho}")
    try:
        documento = fitz.open(caminho)
    except Exception as erro:
        raise ErroExtracao(f"Nao foi possivel abrir o PDF: {erro}") from erro

    with documento:
        if not documento.is_pdf:
            raise ErroExtracao("O arquivo selecionado nao e um PDF valido.")
        if documento.needs_pass:
            raise ErroExtracao("O PDF esta protegido por senha.")

        encontrados: list[Candidato] = []
        total = documento.page_count
        print(f"Processando {total} pagina(s)...")
        for indice, pagina in enumerate(documento, start=1):
            imagem = renderizar_pagina(pagina, dpi)
            candidatos = detectar_tabuleiros(imagem, pagina=indice)
            encontrados.extend(candidatos)
            print(f"Pagina {indice}/{total}: {len(candidatos)} diagrama(s)")
            if progresso is not None:
                progresso(indice, total, len(encontrados))
    return total, sorted(encontrados, key=lambda item: (item.pagina, item.y, item.x))


def criar_pdf_a4(candidatos: Sequence[Candidato], caminho_saida: os.PathLike[str] | str) -> Path:
    if not candidatos:
        raise ErroExtracao("Nenhum tabuleiro foi encontrado; o PDF de saida nao foi criado.")

    saida = Path(caminho_saida).expanduser().resolve()
    if saida.suffix.lower() != ".pdf":
        saida = saida.with_suffix(".pdf")
    saida.parent.mkdir(parents=True, exist_ok=True)

    documento = fitz.open()
    largura_a4, altura_a4 = TAMANHO_A4
    margem = 50.0
    lado = min(largura_a4 - 2 * margem, altura_a4 - 2 * margem)
    x0 = (largura_a4 - lado) / 2
    y0 = (altura_a4 - lado) / 2
    destino = fitz.Rect(x0, y0, x0 + lado, y0 + lado)

    try:
        for candidato in candidatos:
            pagina = documento.new_page(width=largura_a4, height=altura_a4)
            sucesso, buffer = cv2.imencode(".png", candidato.imagem)
            if not sucesso:
                raise ErroExtracao("Falha ao codificar um dos diagramas.")
            pagina.insert_image(destino, stream=buffer.tobytes(), keep_proportion=True)

        descritor, temporario = tempfile.mkstemp(prefix="diagramas_", suffix=".pdf", dir=saida.parent)
        os.close(descritor)
        try:
            documento.save(temporario, garbage=4, deflate=True)
            os.replace(temporario, saida)
        finally:
            if os.path.exists(temporario):
                os.unlink(temporario)
    finally:
        documento.close()
    return saida


def processar_pdf(
    caminho_entrada: os.PathLike[str] | str,
    caminho_saida: os.PathLike[str] | str,
    dpi: int = DPI_PADRAO,
    progresso: Callable[[int, int, int], None] | None = None,
) -> ResultadoExtracao:
    total_paginas, candidatos = detectar_no_pdf(caminho_entrada, dpi=dpi, progresso=progresso)
    if not candidatos:
        return ResultadoExtracao(total_paginas, 0, None)
    saida = criar_pdf_a4(candidatos, caminho_saida)
    return ResultadoExtracao(total_paginas, len(candidatos), saida)


def escolher_pdf_entrada() -> str:
    from tkinter import Tk, filedialog

    raiz = Tk()
    raiz.withdraw()
    raiz.update()
    try:
        return filedialog.askopenfilename(
            title="Selecione o livro em PDF",
            filetypes=[("Arquivos PDF", "*.pdf"), ("Todos os arquivos", "*.*")],
        )
    finally:
        raiz.destroy()


def escolher_pdf_saida(pasta_inicial: str | None = None) -> str:
    from tkinter import Tk, filedialog

    raiz = Tk()
    raiz.withdraw()
    raiz.update()
    try:
        return filedialog.asksaveasfilename(
            title="Salvar PDF com os diagramas",
            initialdir=pasta_inicial,
            initialfile="Diagramas_Livro.pdf",
            defaultextension=".pdf",
            filetypes=[("Arquivos PDF", "*.pdf")],
        )
    finally:
        raiz.destroy()


def executar_com_interface(
    selecionar_entrada: Callable[[], str] = escolher_pdf_entrada,
    selecionar_saida: Callable[[str | None], str] = escolher_pdf_saida,
) -> int:
    entrada = selecionar_entrada()
    if not entrada:
        print("Selecao do livro cancelada.")
        return 1
    saida = selecionar_saida(str(Path(entrada).parent))
    if not saida:
        print("Selecao do arquivo de saida cancelada.")
        return 1

    try:
        resultado = processar_pdf(entrada, saida)
    except ErroExtracao as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 2
    except Exception as erro:  # protecao para falhas inesperadas de bibliotecas
        print(f"Erro inesperado: {erro}", file=sys.stderr)
        return 3

    if resultado.diagramas_encontrados == 0:
        print("Nenhum tabuleiro foi encontrado. Nenhum PDF de saida foi criado.")
        return 4
    print(f"Concluido: {resultado.diagramas_encontrados} diagrama(s).")
    print(f"Arquivo salvo em: {resultado.arquivo_saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(executar_com_interface())
