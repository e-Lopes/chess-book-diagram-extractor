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
LIMIAR_PADRAO = 0.20
LIMIAR_ALTA_SENSIBILIDADE = 0.15
TAMANHO_A4 = fitz.paper_size("a4")


class ErroExtracao(RuntimeError):
    """Erro que pode ser apresentado diretamente para a pessoa usuaria."""


class ExtracaoCancelada(ErroExtracao):
    """Interrupção solicitada pela pessoa usuária."""


def _verificar_cancelamento(cancelado: Callable[[], bool] | None) -> None:
    if cancelado is not None and cancelado():
        raise ExtracaoCancelada("A extração foi cancelada.")


@dataclass
class Candidato:
    pagina: int
    quadro: np.ndarray
    imagem: np.ndarray
    confianca: float
    quadro_pdf: tuple[tuple[float, float], ...] = ()

    @property
    def x(self) -> float:
        return float(np.min(self.quadro[:, 0]))

    @property
    def y(self) -> float:
        return float(np.min(self.quadro[:, 1]))


@dataclass(frozen=True)
class AnotacaoSaida:
    posicao: str | None
    girado: bool = False
    possivel_falso_positivo: bool = False
    excluir: bool = False
    lado_a_jogar: str = "w"


@dataclass(frozen=True)
class ResultadoExtracao:
    paginas_processadas: int
    diagramas_encontrados: int
    arquivo_saida: Path | None
    anotacoes_confirmadas: int = 0
    anotacoes_pendentes: int = 0


def _ordenar_pontos(pontos: np.ndarray) -> np.ndarray:
    pontos = np.asarray(pontos, dtype=np.float32).reshape(4, 2)
    if not np.isfinite(pontos).all() or len(np.unique(pontos, axis=0)) != 4:
        raise ValueError("O quadro precisa ter quatro pontos distintos e finitos.")
    centro = pontos.mean(axis=0)
    angulos = np.arctan2(pontos[:, 1] - centro[1], pontos[:, 0] - centro[0])
    ordenados = pontos[np.argsort(angulos)]
    # Ordenar por soma/diferença separadamente repetia cantos em losangos.
    inicio = min(range(4), key=lambda i: (float(ordenados[i].sum()), float(ordenados[i, 1])))
    ordenados = np.roll(ordenados, -inicio, axis=0)
    if not cv2.isContourConvex(ordenados) or cv2.contourArea(ordenados) < 1.0:
        raise ValueError("O quadro precisa ser um quadrilátero convexo com área positiva.")
    return ordenados


def _ajustar_quadro_ao_contorno(quadro: np.ndarray, contorno: np.ndarray) -> np.ndarray:
    """Ajusta retas aos lados, evitando cantos imprecisos da simplificação."""
    pontos = contorno.reshape(-1, 2).astype(np.float32)
    retas: list[tuple[np.ndarray, np.ndarray]] = []
    for inicio, fim in zip(quadro, np.roll(quadro, -1, axis=0)):
        vetor = fim - inicio
        comprimento = float(np.linalg.norm(vetor))
        direcao = vetor / comprimento
        projecao = (pontos - inicio) @ direcao
        distancia = np.abs((pontos[:, 0] - inicio[0]) * direcao[1] - (pontos[:, 1] - inicio[1]) * direcao[0])
        selecionados = pontos[
            (projecao > comprimento * 0.1) & (projecao < comprimento * 0.9)
            & (distancia < max(2.0, comprimento * 0.035))
        ]
        if len(selecionados) < 4 or np.ptp(selecionados @ direcao) < comprimento * 0.4:
            return quadro
        reta = cv2.fitLine(selecionados, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        retas.append((reta[:2], reta[2:]))
    cantos = []
    for indice in range(4):
        direcao_a, origem_a = retas[indice - 1]
        direcao_b, origem_b = retas[indice]
        matriz = np.column_stack((direcao_a, -direcao_b))
        if abs(float(np.linalg.det(matriz))) < 0.1:
            return quadro
        parametro = np.linalg.solve(matriz, origem_b - origem_a)[0]
        cantos.append(origem_a + parametro * direcao_a)
    ajustado = np.asarray(cantos, dtype=np.float32)
    if np.max(np.linalg.norm(ajustado - quadro, axis=1)) > _lado_do_quadro(quadro) * 0.06:
        return quadro
    try:
        return _ordenar_pontos(ajustado)
    except ValueError:
        return quadro


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
        casas = normalizada.reshape(8, 40, 8, 40).transpose(0, 2, 1, 3)
        assinatura = np.percentile(casas[:, :, 6:-6, 6:-6], 30, axis=(2, 3)).astype(np.float32)
        cantos = np.stack([casas[:, :, y:y + 6, x:x + 6].reshape(8, 8, -1)
                          for y in (6, 28) for x in (6, 28)], axis=2)
        # Peças pretas grandes podem dominar o centro de casas hachuradas.
        # Os quatro cantos fornecem uma segunda estimativa do fundo da grade.
        # O canto menos escurecido resiste a bases largas e coroas que invadem
        # até três cantos; a hachura do fundo continua presente no restante.
        assinatura_cantos = np.percentile(cantos, 30, axis=3).max(axis=2).astype(np.float32)
        for assinatura_atual in (assinatura, assinatura_cantos):
            mediana_a = float(np.median(assinatura_atual[paridade]))
            mediana_b = float(np.median(assinatura_atual[~paridade]))
            contraste = abs(mediana_a - mediana_b) / 255.0
            centrada = assinatura_atual - float(np.mean(assinatura_atual))
            denominador = float(np.linalg.norm(centrada) * np.linalg.norm(ideal))
            correlacao = abs(float(np.sum(centrada * ideal)) / denominador) if denominador else 0.0

            escura = paridade if mediana_a < mediana_b else ~paridade
            sinais = np.where(escura, 1.0, -1.0)
            horizontais = np.diff(assinatura_atual, axis=1) * sinais[:, :-1]
            verticais = np.diff(assinatura_atual, axis=0) * sinais[:-1, :]
            consistencia = float((np.count_nonzero(horizontais >= 3.0)
                                  + np.count_nonzero(verticais >= 3.0)) / 112)
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


def pontuar_tabuleiro(recorte: np.ndarray, alta_sensibilidade: bool = False) -> float:
    """Retorna uma confianca entre 0 e 1 para a estrutura de tabuleiro 8x8."""
    if recorte.size == 0 or min(recorte.shape[:2]) < 64:
        return 0.0
    cinza_original = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY) if recorte.ndim == 3 else recorte
    cinza_original = cv2.resize(cinza_original, (320, 320), interpolation=cv2.INTER_AREA)
    correlacao, contraste, consistencia = _evidencia_grade_8x8(cinza_original)

    # A alternancia bidimensional e obrigatoria. Molduras, fotografias de uma
    # peca e tabelas de texto nao podem compensar a ausencia desta estrutura.
    minimo_correlacao = 0.21 if alta_sensibilidade else 0.34
    minimo_contraste = 0.018 if alta_sensibilidade else 0.028
    minimo_consistencia = 0.55 if alta_sensibilidade else 0.62
    if (
        correlacao < minimo_correlacao
        or contraste < minimo_contraste
        or consistencia < minimo_consistencia
    ):
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
    minimo_continuidade = 0.24 if alta_sensibilidade else 0.32
    minimo_cobertura = 0.14 if alta_sensibilidade else 0.20
    if continuidade < minimo_continuidade and cobertura < minimo_cobertura:
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
    adaptativa = cv2.adaptiveThreshold(
        borrada,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        41,
        11,
    )
    yield adaptativa
    # Hachuras e coordenadas podem unir-se à moldura e fazer minAreaRect
    # inclinar um tabuleiro reto. Linhas longas preservam os quatro lados,
    # removendo as diagonais curtas do preenchimento e os glifos ao redor.
    comprimento = max(45, int(min(cinza.shape) * 0.045 * 0.70))
    horizontais = cv2.morphologyEx(adaptativa, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (comprimento, 1)))
    verticais = cv2.morphologyEx(adaptativa, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, comprimento)))
    yield cv2.bitwise_or(horizontais, verticais)


def _quadros_candidatos(imagem: np.ndarray) -> list[np.ndarray]:
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    menor_dimensao = min(cinza.shape)
    lado_minimo = max(64, int(menor_dimensao * 0.045))
    lado_maximo = int(menor_dimensao * 1.02)
    quadros: list[np.ndarray] = []

    for mascara in _mascaras_de_busca(cinza):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        fechada = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, kernel, iterations=2)
        contornos, _ = cv2.findContours(fechada, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        for contorno in contornos:
            _, _, largura_caixa, altura_caixa = cv2.boundingRect(contorno)
            if min(largura_caixa, altura_caixa) < lado_minimo:
                continue
            perimetro = cv2.arcLength(contorno, True)
            if perimetro <= 0:
                continue
            aproximado = cv2.approxPolyDP(contorno, 0.025 * perimetro, True)
            if len(aproximado) == 4 and cv2.isContourConvex(aproximado):
                quadro = aproximado.reshape(4, 2).astype(np.float32)
            else:
                retangulo = cv2.minAreaRect(contorno)
                quadro = cv2.boxPoints(retangulo).astype(np.float32)

            try:
                q = _ordenar_pontos(quadro)
            except ValueError:
                continue
            larguras = [np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3])]
            alturas = [np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1])]
            largura, altura = float(np.mean(larguras)), float(np.mean(alturas))
            if min(largura, altura) < lado_minimo or max(largura, altura) > lado_maximo:
                continue
            if max(largura, altura) / max(1.0, min(largura, altura)) > 1.18:
                continue
            if cv2.contourArea(q.astype(np.float32)) < lado_minimo**2 * 0.7:
                continue
            q = _ajustar_quadro_ao_contorno(q, contorno)
            quadros.append(q)
    return quadros


def _quadros_de_imagens_pdf(pagina: fitz.Page, dpi: int) -> list[np.ndarray]:
    """Converte caixas de imagens aproximadamente quadradas em coordenadas renderizadas."""
    escala = dpi / 72.0
    menor_dimensao = min(pagina.rect.width, pagina.rect.height) * escala
    lado_minimo = max(64.0, menor_dimensao * 0.045)
    lado_maximo = menor_dimensao * 1.02
    quadros: list[np.ndarray] = []
    try:
        informacoes = pagina.get_image_info()
    except (RuntimeError, ValueError):
        return quadros
    for informacao in informacoes:
        transformacao = fitz.Matrix(informacao["transform"])
        pontos = [fitz.Point(x, y) * transformacao * pagina.rotation_matrix
                  for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
        quadro = np.array([(p.x * escala, p.y * escala) for p in pontos], dtype=np.float32)
        try:
            quadro = _ordenar_pontos(quadro)
        except ValueError:
            continue
        lados = np.linalg.norm(quadro - np.roll(quadro, -1, axis=0), axis=1)
        largura, altura = float(np.mean(lados[::2])), float(np.mean(lados[1::2]))
        if min(largura, altura) < lado_minimo or max(largura, altura) > lado_maximo:
            continue
        if max(largura, altura) / max(1.0, min(largura, altura)) > 1.20:
            continue
        # Não estende recortes além da página usando pixels replicados.
        if (quadro.min(axis=0) < -1).any() or (quadro.max(axis=0) >
                np.array([pagina.rect.width, pagina.rect.height]) * escala + 1).any():
            continue
        quadros.append(quadro)
    return quadros


def _caixa(quadro: np.ndarray) -> tuple[float, float, float, float]:
    return (
        float(np.min(quadro[:, 0])),
        float(np.min(quadro[:, 1])),
        float(np.max(quadro[:, 0])),
        float(np.max(quadro[:, 1])),
    )


def _areas_sobrepostas(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    a, b = _ordenar_pontos(a), _ordenar_pontos(b)
    inter = float(cv2.intersectConvexConvex(a, b)[0])
    return cv2.contourArea(a), cv2.contourArea(b), inter


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    area_a, area_b, inter = _areas_sobrepostas(a, b)
    uniao = area_a + area_b - inter
    return inter / uniao if uniao > 0 else 0.0


def _sobreposicao_menor(a: np.ndarray, b: np.ndarray) -> float:
    """Fracao da menor caixa coberta; identifica contornos aninhados."""
    area_a, area_b, inter = _areas_sobrepostas(a, b)
    menor_area, maior_area = min(area_a, area_b), max(area_a, area_b)
    # Uma moldura envolvendo vários diagramas não é duplicata de cada um.
    return inter / menor_area if menor_area > 0 and menor_area / maior_area >= 0.5 else 0.0


def _ordenar_leitura(candidatos: Sequence[Candidato]) -> list[Candidato]:
    ordenados: list[Candidato] = []
    linha: list[Candidato] = []
    for candidato in sorted(candidatos, key=lambda item: (item.pagina, item.y, item.x)):
        if linha:
            ancora = linha[0]
            altura = min(_caixa(ancora.quadro)[3] - ancora.y,
                         _caixa(candidato.quadro)[3] - candidato.y)
            if candidato.pagina != ancora.pagina or candidato.y - ancora.y > altura * 0.15:
                ordenados.extend(sorted(linha, key=lambda item: item.x))
                linha = []
        linha.append(candidato)
    ordenados.extend(sorted(linha, key=lambda item: item.x))
    return ordenados


def _mesmo_diagrama(candidato: Candidato, existente: Candidato, limite_iou: float) -> bool:
    if candidato.pagina != existente.pagina:
        return False
    area_a, area_b, inter = _areas_sobrepostas(candidato.quadro, existente.quadro)
    if inter / (area_a + area_b - inter) >= limite_iou:
        return True
    menor, maior = min(area_a, area_b), max(area_a, area_b)
    if menor / maior >= 0.5 and inter / menor >= 0.78:
        return True
    # Um contorno parcial sem grade dentro de um tabuleiro confirmado também
    # é redundante. Uma moldura maior contendo diagramas distintos permanece.
    return (existente.confianca >= LIMIAR_PADRAO and candidato.confianca < LIMIAR_PADRAO
            and inter / area_a >= 0.90)


def remover_duplicados(candidatos: Sequence[Candidato], limite_iou: float = 0.55) -> list[Candidato]:
    mantidos: list[Candidato] = []
    for candidato in sorted(candidatos, key=lambda item: item.confianca, reverse=True):
        if not any(_mesmo_diagrama(candidato, existente, limite_iou) for existente in mantidos):
            mantidos.append(candidato)
    return _ordenar_leitura(mantidos)


def detectar_tabuleiros(
    imagem: np.ndarray,
    pagina: int = 1,
    limiar: float = LIMIAR_PADRAO,
    alta_sensibilidade: bool = False,
    quadros_adicionais: Sequence[np.ndarray] = (),
    aceitar_quadrados: bool = False,
) -> list[Candidato]:
    encontrados: list[Candidato] = []
    quadros = [*_quadros_candidatos(imagem), *quadros_adicionais]
    for quadro in quadros:
        recorte = corrigir_perspectiva(imagem, quadro)
        confianca = pontuar_tabuleiro(recorte, alta_sensibilidade=alta_sensibilidade)
        if aceitar_quadrados or confianca >= limiar:
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
    cancelado: Callable[[], bool] | None = None,
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

        encontrados_por_pagina: dict[int, list[Candidato]] = {}
        total = documento.page_count
        print(f"Processando {total} pagina(s)...")
        for indice, pagina in enumerate(documento, start=1):
            _verificar_cancelamento(cancelado)
            imagem = renderizar_pagina(pagina, dpi)
            candidatos = detectar_tabuleiros(
                imagem,
                pagina=indice,
                quadros_adicionais=_quadros_de_imagens_pdf(pagina, dpi),
            )
            for candidato in candidatos:
                candidato.quadro_pdf = tuple(tuple(float(v) for v in p)
                                             for p in candidato.quadro * (72 / dpi))
            _verificar_cancelamento(cancelado)
            encontrados_por_pagina[indice] = candidatos
            print(f"Pagina {indice}/{total}: {len(candidatos)} diagrama(s)")
            if progresso is not None:
                progresso(
                    indice,
                    total,
                    sum(len(itens) for itens in encontrados_por_pagina.values()),
                )

    encontrados = [
        candidato
        for numero in sorted(encontrados_por_pagina)
        for candidato in encontrados_por_pagina[numero]
    ]
    return total, _ordenar_leitura(encontrados)


def criar_pdf_a4(
    candidatos: Sequence[Candidato],
    caminho_saida: os.PathLike[str] | str,
    anotacoes: Sequence[AnotacaoSaida] | None = None,
    cancelado: Callable[[], bool] | None = None,
) -> Path:
    if not candidatos:
        raise ErroExtracao("Nenhum tabuleiro foi encontrado; o PDF de saida nao foi criado.")
    if anotacoes is not None and len(anotacoes) != len(candidatos):
        raise ErroExtracao("A quantidade de anotações não corresponde aos diagramas encontrados.")

    candidatos_pdf = list(candidatos)
    anotacoes_pdf = list(anotacoes) if anotacoes is not None else None
    if anotacoes_pdf is not None:
        mantidos = [
            (candidato, anotacao)
            for candidato, anotacao in zip(candidatos_pdf, anotacoes_pdf)
            if not anotacao.excluir
        ]
        if not mantidos:
            raise ErroExtracao("Todos os recortes foram marcados como não sendo tabuleiros.")
        candidatos_pdf = [candidato for candidato, _anotacao in mantidos]
        anotacoes_pdf = [anotacao for _candidato, anotacao in mantidos]

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

    def inserir_texto_centralizado(
        pagina: fitz.Page,
        texto: str,
        y: float,
        tamanho_fonte: float = 9.0,
        fonte: str = "cour",
        tamanho_minimo: float = 7.0,
    ) -> None:
        largura_texto = fitz.get_text_length(texto, fontname=fonte, fontsize=tamanho_fonte)
        if largura_texto > largura_a4 - 2 * margem:
            tamanho_fonte = max(
                tamanho_minimo,
                tamanho_fonte * (largura_a4 - 2 * margem) / largura_texto,
            )
            largura_texto = fitz.get_text_length(texto, fontname=fonte, fontsize=tamanho_fonte)
        x_texto = max(margem, (largura_a4 - largura_texto) / 2)
        pagina.insert_text(
            fitz.Point(x_texto, y),
            texto,
            fontname=fonte,
            fontsize=tamanho_fonte,
            color=(0.10, 0.13, 0.18),
        )

    try:
        for indice, candidato in enumerate(candidatos_pdf):
            _verificar_cancelamento(cancelado)
            pagina = documento.new_page(width=largura_a4, height=altura_a4)
            anotacao = anotacoes_pdf[indice] if anotacoes_pdf is not None else None
            imagem = cv2.rotate(candidato.imagem, cv2.ROTATE_180) if anotacao and anotacao.girado else candidato.imagem
            sucesso, buffer = cv2.imencode(".png", imagem)
            if not sucesso:
                raise ErroExtracao("Falha ao codificar um dos diagramas.")
            pagina.insert_image(destino, stream=buffer.tobytes(), keep_proportion=True)
            if anotacao is not None:
                conteudo = anotacao.posicao if anotacao.posicao else "posição não informada"
                inserir_texto_centralizado(
                    pagina,
                    f"{conteudo} {anotacao.lado_a_jogar}",
                    destino.y1 + 24,
                    tamanho_fonte=13.0,
                    fonte="cobo",
                    tamanho_minimo=10.0,
                )
            inserir_texto_centralizado(
                pagina,
                f"Página original (do pdf): {candidato.pagina}",
                destino.y1 + (48 if anotacao is not None else 24),
                tamanho_fonte=13.0,
                fonte="hebo",
                tamanho_minimo=11.0,
            )
            if anotacoes is None:
                inserir_texto_centralizado(
                    pagina,
                    f"Confiança da detecção: {candidato.confianca * 100:.1f}%",
                    destino.y1 + 42,
                    tamanho_fonte=9.0,
                    fonte="helv",
                )

        if anotacoes_pdf is not None:
            # Acrescenta um índice textual na mesma ordem das páginas dos
            # diagramas. Cada posição ocupa duas linhas: Forsyth e lado a jogar.
            margem_indice = 42.0
            tamanho_fonte = 9.0
            altura_linha = 13.0
            altura_item = 31.0
            y_inicial = margem_indice + tamanho_fonte
            y_limite = altura_a4 - margem_indice
            pagina_indice: fitz.Page | None = None
            y_linha = y_inicial

            for anotacao in anotacoes_pdf:
                _verificar_cancelamento(cancelado)
                if pagina_indice is None or y_linha + altura_linha > y_limite:
                    pagina_indice = documento.new_page(width=largura_a4, height=altura_a4)
                    y_linha = y_inicial
                texto = f"{anotacao.posicao or 'posição não informada'} {anotacao.lado_a_jogar}"
                pagina_indice.insert_text(
                    fitz.Point(margem_indice, y_linha),
                    texto,
                    fontname="cour",
                    fontsize=tamanho_fonte,
                    color=(0.10, 0.13, 0.18),
                )
                pagina_indice.insert_text(
                    fitz.Point(margem_indice, y_linha + altura_linha),
                    "White to move" if anotacao.lado_a_jogar == "w" else "Black to move",
                    fontname="helv",
                    fontsize=tamanho_fonte,
                    color=(0.10, 0.13, 0.18),
                )
                y_linha += altura_item

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


def carregar_diagramas_do_pdf_extraido(
    caminho_pdf: os.PathLike[str] | str,
    originais: Sequence[Candidato],
    cancelado: Callable[[], bool] | None = None,
) -> list[Candidato]:
    """Relê do PDF de extração a imagem usada em cada página A4."""
    caminho = Path(caminho_pdf)
    try:
        documento = fitz.open(caminho)
    except Exception as erro:
        raise ErroExtracao(f"Não foi possível reler o PDF extraído: {erro}") from erro

    with documento:
        if documento.page_count != len(originais):
            raise ErroExtracao("O PDF extraído não corresponde aos diagramas detectados.")
        resultado: list[Candidato] = []
        for indice, original in enumerate(originais):
            _verificar_cancelamento(cancelado)
            imagens = documento[indice].get_images(full=True)
            if not imagens:
                raise ErroExtracao(f"A página {indice + 1} do PDF extraído não contém um diagrama.")
            maior = max(imagens, key=lambda item: int(item[2]) * int(item[3]))
            dados = documento.extract_image(int(maior[0])).get("image")
            if not isinstance(dados, bytes):
                raise ErroExtracao(f"Não foi possível ler o diagrama {indice + 1} do PDF extraído.")
            matriz = np.frombuffer(dados, dtype=np.uint8)
            imagem = cv2.imdecode(matriz, cv2.IMREAD_COLOR)
            if imagem is None:
                raise ErroExtracao(f"Não foi possível decodificar o diagrama {indice + 1}.")
            resultado.append(
                Candidato(
                    pagina=original.pagina,
                    quadro=original.quadro.copy(),
                    quadro_pdf=original.quadro_pdf,
                    imagem=imagem,
                    confianca=original.confianca,
                )
            )
    return resultado


def processar_pdf(
    caminho_entrada: os.PathLike[str] | str,
    caminho_saida: os.PathLike[str] | str,
    dpi: int = DPI_PADRAO,
    progresso: Callable[[int, int, int], None] | None = None,
    cancelado: Callable[[], bool] | None = None,
) -> ResultadoExtracao:
    total_paginas, candidatos = detectar_no_pdf(
        caminho_entrada,
        dpi=dpi,
        progresso=progresso,
        cancelado=cancelado,
    )
    if not candidatos:
        return ResultadoExtracao(total_paginas, 0, None)
    saida = criar_pdf_a4(candidatos, caminho_saida, cancelado=cancelado)
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
