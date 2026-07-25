"""Reconhecimento e revisão da posição das peças em notação Forsyth portuguesa."""

from __future__ import annotations

import hashlib
import base64
import json
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np


ALFABETO_MODELO = "1KQRBNPkqrbnp"
PECAS_PADRAO = "KQRBNPkqrbnp"
PECAS_PORTUGUES = "RDTBCPrdtbcp"
IDIOMAS_NOTACAO = ("pt", "en")
MAPA_PORTUGUES = str.maketrans("KQRBNPkqrbnp", "RDTBCPrdtbcp")
LIMIAR_CONFIANCA = 0.70
LIMIAR_REFERENCIA = 0.85
MARGEM_REFERENCIA = 0.30
LIMIAR_AMBIGUIDADE = 0.70
MARGEM_AMBIGUIDADE = 0.20
VANTAGEM_MINIMA_REVISAO = 0.10
PARES_CONFUSAO = {
    frozenset(("P", "N")),
    frozenset(("p", "n")),
    frozenset(("p", "b")),
    frozenset(("B", "Q")),
}
CASA_CLARA = 0
CASA_ESCURA = 1
SHA256_MODELO = "883F6A8E639E6D6B6399B3FDA0508AD772E3C6F9CEFA2E678A13F27B9FA6248D"
NOME_MODELO = "chess-tiles-v2.onnx"


def caminho_recurso(*partes: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*partes)


def caminho_modelo_padrao() -> Path:
    return caminho_recurso("models", NOME_MODELO)


def _expandir_linha(linha: str, pecas: str) -> list[str]:
    casas: list[str] = []
    for caractere in linha:
        if caractere in "12345678":
            casas.extend([""] * int(caractere))
        elif caractere in pecas:
            casas.append(caractere)
        else:
            raise ValueError(f"Caractere inválido: {caractere}")
    if len(casas) != 8:
        raise ValueError("Cada linha precisa representar exatamente 8 casas.")
    return casas


def expandir_posicao(posicao: str, pecas: str = PECAS_PORTUGUES) -> list[list[str]]:
    linhas = posicao.strip().split("/")
    if len(linhas) != 8:
        raise ValueError("A posição precisa ter 8 linhas separadas por '/'.")
    return [_expandir_linha(linha, pecas) for linha in linhas]


def compactar_tabuleiro(tabuleiro: Sequence[Sequence[str]]) -> str:
    if len(tabuleiro) != 8 or any(len(linha) != 8 for linha in tabuleiro):
        raise ValueError("O tabuleiro precisa ter 8 linhas de 8 casas.")
    linhas: list[str] = []
    for linha in tabuleiro:
        partes: list[str] = []
        vazias = 0
        for casa in linha:
            if not casa:
                vazias += 1
                continue
            if vazias:
                partes.append(str(vazias))
                vazias = 0
            partes.append(casa)
        if vazias:
            partes.append(str(vazias))
        linhas.append("".join(partes))
    return "/".join(linhas)


def pecas_do_idioma(idioma: str) -> str:
    if idioma == "pt":
        return PECAS_PORTUGUES
    if idioma == "en":
        return PECAS_PADRAO
    raise ValueError(f"Idioma de notação inválido: {idioma}")


def normalizar_posicao(posicao: str, idioma: str = "pt") -> str:
    return compactar_tabuleiro(expandir_posicao(posicao, pecas_do_idioma(idioma)))


def validar_posicao(posicao: str, idioma: str = "pt") -> tuple[bool, str]:
    if not posicao.strip():
        return False, "Informe a posição das peças."
    try:
        normalizar_posicao(posicao, idioma)
    except ValueError as erro:
        return False, str(erro)
    return True, "Posição válida."


def aviso_plausibilidade(posicao: str, idioma: str = "pt") -> str:
    try:
        tabuleiro = expandir_posicao(posicao, pecas_do_idioma(idioma))
    except ValueError as erro:
        return str(erro)
    pecas = [casa for linha in tabuleiro for casa in linha if casa]
    rei_branco, rei_preto = ("R", "r") if idioma == "pt" else ("K", "k")
    if pecas.count(rei_branco) != 1 or pecas.count(rei_preto) != 1:
        return (
            "Possível falso positivo: talvez esta imagem não seja um diagrama/tabuleiro. "
            "A posição deveria ter exatamente um rei de cada cor."
        )
    brancas = sum(peca.isupper() for peca in pecas)
    pretas = sum(peca.islower() for peca in pecas)
    if len(pecas) > 32 or brancas > 16 or pretas > 16:
        return (
            "Possível falso positivo: talvez esta imagem não seja um diagrama/tabuleiro. "
            "A quantidade de peças reconhecidas é muito improvável."
        )
    if pecas.count("P") > 8 or pecas.count("p") > 8:
        return (
            "Possível falso positivo: talvez esta imagem não seja um diagrama/tabuleiro. "
            "Foram reconhecidos mais de oito peões da mesma cor."
        )
    return ""


def girar_posicao(posicao: str, idioma: str = "pt") -> str:
    tabuleiro = expandir_posicao(posicao, pecas_do_idioma(idioma))
    return compactar_tabuleiro([list(reversed(linha)) for linha in reversed(tabuleiro)])


def converter_padrao_para_portugues(posicao: str) -> str:
    tabuleiro = expandir_posicao(posicao, PECAS_PADRAO)
    convertido = [[casa.translate(MAPA_PORTUGUES) for casa in linha] for linha in tabuleiro]
    return compactar_tabuleiro(convertido)


def converter_padrao_para_idioma(posicao: str, idioma: str) -> str:
    if idioma == "pt":
        return converter_padrao_para_portugues(posicao)
    if idioma == "en":
        return normalizar_posicao(posicao, "en")
    raise ValueError(f"Idioma de notação inválido: {idioma}")


def converter_idioma_para_padrao(posicao: str, idioma: str) -> str:
    normalizada = normalizar_posicao(posicao, idioma)
    if idioma == "en":
        return normalizada
    mapa_inverso = str.maketrans("RDTBCPrdtbcp", "KQRBNPkqrbnp")
    return normalizada.translate(mapa_inverso)


def _compactar_classes(classes: Sequence[str]) -> str:
    if len(classes) != 64:
        raise ValueError("O classificador precisa retornar 64 casas.")
    linhas: list[list[str]] = []
    for indice_linha in range(7, -1, -1):
        inicio = indice_linha * 8
        linhas.append(["" if casa == "1" else casa for casa in classes[inicio : inicio + 8]])
    return compactar_tabuleiro(linhas)


def paridade_casa_modelo(indice_casa: int) -> int:
    """0=clara e 1=escura; a8 (canto superior esquerdo) é sempre clara."""
    if not 0 <= indice_casa < 64:
        raise ValueError("O índice da casa precisa estar entre 0 e 63.")
    coluna = indice_casa % 8
    linha_modelo = indice_casa // 8
    linha_imagem = 7 - linha_modelo
    return (linha_imagem + coluna) % 2


def _decodificar_com_ajustes(
    probabilidades: np.ndarray,
) -> tuple[str, list[float], float, float, int, np.ndarray]:
    matriz = np.asarray(probabilidades, dtype=np.float32).reshape(64, 13)
    indices = np.argmax(matriz, axis=1)
    ajustes = 0
    # Alguns diagramas tipográficos antigos desenham a cabeça do peão com um
    # contorno parecido com o cavalo do corpus de treinamento. Só corrigimos
    # quando "cavalo" é uma leitura fraca e "peão" ficou muito próximo; casos
    # claros e cavalos de alta confiança permanecem intocados.
    for classe_cavalo, classe_peao, linha_inicial_peoes in (
        (5, 6, 2),
        (11, 12, 7),
    ):
        for indice_casa in range(64):
            confianca_cavalo = float(matriz[indice_casa, classe_cavalo])
            confianca_peao = float(matriz[indice_casa, classe_peao])
            fileira = indice_casa // 8 + 1
            if indices[indice_casa] == classe_cavalo:
                proximidade_suficiente = (
                    confianca_peao >= confianca_cavalo * 0.50
                    if fileira == linha_inicial_peoes
                    else confianca_peao >= confianca_cavalo * 0.80
                )
                if (
                    confianca_cavalo < 0.70
                    and confianca_peao >= 0.15
                    and proximidade_suficiente
                ):
                    indices[indice_casa] = classe_peao
                    ajustes += 1
            elif indices[indice_casa] == classe_peao:
                # No sentido inverso, só mexemos em um empate praticamente
                # técnico. Isso cobre cavalos impressos com base estreita sem
                # converter peões reconhecidos com segurança.
                if (
                    confianca_peao < 0.60
                    and confianca_cavalo >= 0.15
                    and confianca_cavalo >= confianca_peao * 0.85
                ):
                    indices[indice_casa] = classe_cavalo
                    ajustes += 1
    confiancas = matriz[np.arange(64), indices].astype(float).tolist()
    classes = [ALFABETO_MODELO[indice] for indice in indices]
    posicao = _compactar_classes(classes)
    return (
        posicao,
        confiancas,
        min(confiancas),
        sum(confiancas) / len(confiancas),
        ajustes,
        indices.copy(),
    )


def decodificar_probabilidades(probabilidades: np.ndarray) -> tuple[str, list[float], float, float]:
    posicao, confiancas, minima, media, _ajustes, _indices = _decodificar_com_ajustes(probabilidades)
    return posicao, confiancas, minima, media


def _media_linhas_peoes(posicao: str) -> tuple[float | None, float | None]:
    tabuleiro = expandir_posicao(posicao, PECAS_PADRAO)
    brancos: list[int] = []
    pretos: list[int] = []
    for indice, linha in enumerate(tabuleiro):
        numero_linha = 8 - indice
        for casa in linha:
            if casa == "P":
                brancos.append(numero_linha)
            elif casa == "p":
                pretos.append(numero_linha)
    media_brancos = sum(brancos) / len(brancos) if brancos else None
    media_pretos = sum(pretos) / len(pretos) if pretos else None
    return media_brancos, media_pretos


def resolver_orientacao(posicao: str) -> tuple[str, bool, bool]:
    """Retorna posição, se foi girada e se a orientação permaneceu ambígua."""
    brancos, pretos = _media_linhas_peoes(posicao)
    if brancos is None or pretos is None:
        return posicao, False, True
    diferenca = pretos - brancos
    if abs(diferenca) < 0.5:
        return posicao, False, True
    if diferenca < 0:
        portuguesa = converter_padrao_para_portugues(posicao)
        girada = girar_posicao(portuguesa)
        # A função pública retorna o alfabeto padrão neste ponto.
        mapa_inverso = str.maketrans("RDTBCPrdtbcp", "KQRBNPkqrbnp")
        return girada.translate(mapa_inverso), True, False
    return posicao, False, False


def _preparar_casas(imagem: np.ndarray, inset: float) -> np.ndarray:
    if imagem.ndim == 3:
        cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    else:
        cinza = imagem
    altura, largura = cinza.shape[:2]
    margem = int(round(min(altura, largura) * inset))
    recorte = cinza[margem : altura - margem, margem : largura - margem] if margem else cinza
    tabuleiro = cv2.resize(recorte, (256, 256), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
    casas = np.empty((64, 1024), dtype=np.float32)
    indice = 0
    for linha_modelo in range(8):
        linha_imagem = 7 - linha_modelo
        for coluna in range(8):
            casa = tabuleiro[
                linha_imagem * 32 : (linha_imagem + 1) * 32,
                coluna * 32 : (coluna + 1) * 32,
            ]
            casas[indice] = casa.reshape(-1)
            indice += 1
    return casas


@dataclass(frozen=True)
class DadosCasa:
    indice: int
    coordenada: str
    paridade: int
    imagem: np.ndarray
    probabilidades: np.ndarray
    classe_original: str
    top3: tuple[str, str, str]
    confianca: float
    margem: float


@dataclass(frozen=True)
class AlteracaoAutomatica:
    indice: int
    coordenada: str
    original: str
    nova: str
    confianca_modelo: float
    similaridade: float
    vantagem: float


@dataclass(frozen=True)
class DuvidaAutomatica:
    indice: int
    coordenada: str
    original: str
    alternativa: str
    similaridade: float


@dataclass(frozen=True)
class ResultadoReconhecimento:
    posicao: str
    confianca_minima: float
    confianca_media: float
    confiavel: bool
    girado: bool
    orientacao_ambigua: bool
    aviso: str = ""
    posicao_original_padrao: str = ""
    casas: tuple[DadosCasa, ...] = ()
    alteracoes_automaticas: tuple[AlteracaoAutomatica, ...] = ()
    duvidas_automaticas: tuple[DuvidaAutomatica, ...] = ()
    possivel_falso_positivo: bool = False


class ReconhecedorForsyth:
    def __init__(
        self,
        caminho_modelo: os.PathLike[str] | str | None = None,
        idioma: str = "pt",
    ) -> None:
        pecas_do_idioma(idioma)
        self.idioma = idioma
        self.caminho_modelo = Path(caminho_modelo or caminho_modelo_padrao())
        if not self.caminho_modelo.is_file():
            raise FileNotFoundError(f"Modelo de reconhecimento não encontrado: {self.caminho_modelo}")
        digest = hashlib.sha256(self.caminho_modelo.read_bytes()).hexdigest().upper()
        if digest != SHA256_MODELO:
            raise RuntimeError("O modelo de reconhecimento falhou na validação SHA-256.")
        try:
            import onnxruntime as ort
        except ImportError as erro:
            raise RuntimeError("O componente onnxruntime não está disponível.") from erro
        self._sessao = ort.InferenceSession(str(self.caminho_modelo), providers=["CPUExecutionProvider"])
        self._entrada = self._sessao.get_inputs()[0].name
        self._saida = self._sessao.get_outputs()[0].name

    def reconhecer(self, imagem: np.ndarray) -> ResultadoReconhecimento:
        melhor: tuple[
            tuple[str, list[float], float, float, int, np.ndarray],
            np.ndarray,
            np.ndarray,
        ] | None = None
        for inset in (0.0, 0.01, 0.02, 0.03, 0.045):
            casas = _preparar_casas(imagem, inset)
            probabilidades = self._sessao.run([self._saida], {self._entrada: casas})[0]
            atual = _decodificar_com_ajustes(probabilidades)
            if melhor is None or atual[3] > melhor[0][3]:
                melhor = (atual, casas.copy(), np.asarray(probabilidades, dtype=np.float32).reshape(64, 13))
        assert melhor is not None
        decodificado, imagens_casas, matriz_probabilidades = melhor
        posicao_padrao, _confiancas, minima, media, ajustes, indices = decodificado
        dados_casas: list[DadosCasa] = []
        for indice_casa in range(64):
            ordem = np.argsort(matriz_probabilidades[indice_casa])[::-1]
            coluna = indice_casa % 8
            linha_modelo = indice_casa // 8
            dados_casas.append(
                DadosCasa(
                    indice=indice_casa,
                    coordenada=f"{chr(ord('a') + coluna)}{linha_modelo + 1}",
                    paridade=paridade_casa_modelo(indice_casa),
                    imagem=imagens_casas[indice_casa].reshape(32, 32).copy(),
                    probabilidades=matriz_probabilidades[indice_casa].copy(),
                    classe_original=ALFABETO_MODELO[int(indices[indice_casa])],
                    top3=tuple(ALFABETO_MODELO[int(item)] for item in ordem[:3]),
                    confianca=float(matriz_probabilidades[indice_casa, indices[indice_casa]]),
                    margem=float(
                        matriz_probabilidades[indice_casa, ordem[0]]
                        - matriz_probabilidades[indice_casa, ordem[1]]
                    ),
                )
            )
        # Os livros processados usam orientação padronizada. A leitura mantém
        # exatamente o topo e a base mostrados no PDF de extrações.
        posicao_orientada, girado, ambigua = posicao_padrao, False, False
        posicao_convertida = converter_padrao_para_idioma(posicao_orientada, self.idioma)
        plausibilidade = aviso_plausibilidade(posicao_convertida, self.idioma)
        motivos: list[str] = []
        if minima < LIMIAR_CONFIANCA:
            motivos.append("Algumas casas tiveram baixa confiança.")
        if ambigua:
            motivos.append("A orientação não pôde ser determinada com segurança.")
        if plausibilidade:
            motivos.append(plausibilidade)
        if ajustes:
            motivos.append(
                f"{ajustes} possível(is) confusão(ões) entre peão e cavalo foram ajustadas."
            )
        return ResultadoReconhecimento(
            posicao=posicao_convertida,
            confianca_minima=minima,
            confianca_media=media,
            confiavel=(
                minima >= LIMIAR_CONFIANCA
                and not ambigua
                and not plausibilidade
                and ajustes == 0
            ),
            girado=girado,
            orientacao_ambigua=ambigua,
            aviso=" ".join(motivos),
            posicao_original_padrao=posicao_padrao,
            casas=tuple(dados_casas),
            possivel_falso_positivo=bool(plausibilidade),
        )


@dataclass(frozen=True)
class ReferenciaCasa:
    classe: str
    paridade: int
    imagem: np.ndarray
    origem_diagrama: int
    manual: bool = False


def _classes_modelo_da_posicao(posicao_padrao: str) -> list[str]:
    tabuleiro = expandir_posicao(posicao_padrao, PECAS_PADRAO)
    return [casa or "1" for linha in reversed(tabuleiro) for casa in linha]


def _penalidade_plausibilidade(classes: Sequence[str]) -> int:
    pecas = [classe for classe in classes if classe != "1"]
    penalidade = abs(pecas.count("K") - 1) * 4 + abs(pecas.count("k") - 1) * 4
    penalidade += max(0, pecas.count("P") - 8) * 2 + max(0, pecas.count("p") - 8) * 2
    brancas = sum(classe.isupper() for classe in pecas)
    pretas = sum(classe.islower() for classe in pecas)
    penalidade += max(0, brancas - 16) + max(0, pretas - 16) + max(0, len(pecas) - 32)
    return penalidade


def _descritor_casa(imagem: np.ndarray, fundo: np.ndarray | None) -> np.ndarray:
    casa = np.asarray(imagem, dtype=np.float32).reshape(32, 32)
    if fundo is not None:
        casa = np.abs(casa - fundo)
    else:
        casa = np.abs(casa - float(np.median(casa)))
    casa = cv2.GaussianBlur(casa, (3, 3), 0)
    minimo, maximo = float(casa.min()), float(casa.max())
    if maximo > minimo:
        casa = (casa - minimo) / (maximo - minimo)
    oito_bits = np.clip(casa * 255.0, 0, 255).astype(np.uint8)
    hog = cv2.HOGDescriptor((32, 32), (16, 16), (8, 8), (8, 8), 9).compute(oito_bits).reshape(-1)
    reduzida = cv2.resize(casa, (16, 16), interpolation=cv2.INTER_AREA).reshape(-1)
    descritor = np.concatenate((hog.astype(np.float32), reduzida.astype(np.float32)))
    norma = float(np.linalg.norm(descritor))
    return descritor / norma if norma > 1e-8 else descritor


def _similaridade(descritor_a: np.ndarray, descritor_b: np.ndarray) -> float:
    return float(np.clip(np.dot(descritor_a, descritor_b), -1.0, 1.0))


class RevisorAutomaticoLivro:
    """Reavalia casas ambíguas usando somente referências do mesmo livro."""

    def __init__(
        self,
        resultados: Sequence[ResultadoReconhecimento],
        idioma: str = "pt",
        referencias_manuais: Sequence[ReferenciaCasa] = (),
        caminho_pdf: os.PathLike[str] | str | None = None,
        pasta_dados: Path | None = None,
    ) -> None:
        self.resultados_originais = list(resultados)
        self.idioma = idioma
        self.caminho_pdf = str(caminho_pdf) if caminho_pdf is not None else None
        self.pasta_dados = pasta_dados
        carregadas = (
            carregar_referencias_manuais(self.caminho_pdf, pasta_dados)
            if self.caminho_pdf is not None and pasta_dados is not None
            else []
        )
        self.referencias_manuais = [*referencias_manuais, *carregadas]
        self.excluidos: set[int] = set()
        self.fundos = self._criar_fundos()
        self.referencias_automaticas = self._criar_referencias_automaticas()
        self._referencias_sujas = False

    def _criar_fundos(self) -> dict[int, np.ndarray]:
        fundos: dict[int, np.ndarray] = {}
        for paridade in (0, 1):
            imagens = [
                casa.imagem
                for resultado in self.resultados_originais
                if not resultado.possivel_falso_positivo
                for casa in resultado.casas
                if casa.paridade == paridade
                and casa.top3[0] == "1"
                and casa.confianca >= LIMIAR_REFERENCIA
                and casa.margem >= MARGEM_REFERENCIA
            ]
            if len(imagens) >= 3:
                fundos[paridade] = np.median(np.stack(imagens), axis=0).astype(np.float32)
        return fundos

    def _criar_referencias_automaticas(self) -> list[ReferenciaCasa]:
        candidatas: dict[tuple[str, int], list[ReferenciaCasa]] = {}
        for indice_diagrama, resultado in enumerate(self.resultados_originais):
            if resultado.possivel_falso_positivo or indice_diagrama in self.excluidos:
                continue
            for casa in resultado.casas:
                if (
                    casa.classe_original == "1"
                    or casa.classe_original != casa.top3[0]
                    or casa.confianca < LIMIAR_REFERENCIA
                    or casa.margem < MARGEM_REFERENCIA
                ):
                    continue
                chave = (casa.classe_original, casa.paridade)
                candidatas.setdefault(chave, []).append(
                    ReferenciaCasa(
                        casa.classe_original,
                        casa.paridade,
                        casa.imagem.copy(),
                        indice_diagrama,
                    )
                )

        referencias: list[ReferenciaCasa] = []
        for (_classe, paridade), grupo in candidatas.items():
            if len(grupo) < 3 or len({item.origem_diagrama for item in grupo}) < 2:
                continue
            selecionadas: list[tuple[ReferenciaCasa, np.ndarray]] = []
            fundo = self.fundos.get(paridade)
            for referencia in grupo:
                descritor = _descritor_casa(referencia.imagem, fundo)
                if len(selecionadas) >= 3 and any(
                    _similaridade(descritor, existente) > 0.998
                    for _item, existente in selecionadas
                ):
                    continue
                selecionadas.append((referencia, descritor))
                if len(selecionadas) >= 24:
                    break
            if len(selecionadas) >= 3:
                referencias.extend(item for item, _descritor in selecionadas)
        return referencias

    def _persistir_referencias(self) -> None:
        if self.caminho_pdf is not None and self.pasta_dados is not None:
            salvar_referencias_manuais(
                self.caminho_pdf,
                self.referencias_manuais,
                self.pasta_dados,
            )

    def registrar_edicao(
        self,
        indice_diagrama: int,
        item: "ItemRevisao",
        posicao_anterior: str,
        posicao_nova: str,
    ) -> int:
        try:
            anterior = _classes_modelo_da_posicao(
                converter_idioma_para_padrao(posicao_anterior, self.idioma)
            )
            nova = _classes_modelo_da_posicao(
                converter_idioma_para_padrao(posicao_nova, self.idioma)
            )
        except ValueError:
            return 0
        adicionadas = 0
        for casa, classe_anterior, classe_nova in zip(item.casas, anterior, nova):
            if classe_anterior == classe_nova:
                continue
            referencia = ReferenciaCasa(
                classe_nova,
                casa.paridade,
                casa.imagem.copy(),
                indice_diagrama,
                manual=True,
            )
            assinatura = hashlib.sha256(
                np.clip(referencia.imagem * 255.0, 0, 255).astype(np.uint8).tobytes()
                + referencia.classe.encode("ascii")
                + bytes((referencia.paridade,))
                + str(referencia.origem_diagrama).encode("ascii")
            ).digest()
            existentes = {
                hashlib.sha256(
                    np.clip(item_existente.imagem * 255.0, 0, 255).astype(np.uint8).tobytes()
                    + item_existente.classe.encode("ascii")
                    + bytes((item_existente.paridade,))
                    + str(item_existente.origem_diagrama).encode("ascii")
                ).digest()
                for item_existente in self.referencias_manuais
            }
            if assinatura not in existentes:
                self.referencias_manuais.append(referencia)
                adicionadas += 1
        if adicionadas:
            self._persistir_referencias()
        return adicionadas

    def definir_exclusao(self, indice_diagrama: int, excluir: bool) -> None:
        if excluir:
            self.excluidos.add(indice_diagrama)
            self.referencias_manuais = [
                referencia
                for referencia in self.referencias_manuais
                if referencia.origem_diagrama != indice_diagrama
            ]
        else:
            self.excluidos.discard(indice_diagrama)
        # A reconstrução envolve centenas de descritores HOG. Ela é adiada
        # para a próxima revisão para que o checkbox da interface responda
        # imediatamente e nunca bloqueie a thread do Tkinter.
        self._referencias_sujas = True
        self._persistir_referencias()

    def revisar_itens(self, itens: Sequence["ItemRevisao"]) -> None:
        if len(itens) != len(self.resultados_originais):
            return
        for item, resultado in zip(itens, self.revisar()):
            if item.editada_manualmente or item.nao_e_tabuleiro:
                continue
            item.posicao = resultado.posicao
            item.aviso = resultado.aviso
            item.alteracoes_automaticas = resultado.alteracoes_automaticas
            item.duvidas_automaticas = resultado.duvidas_automaticas
            item.confiavel = resultado.confiavel

    def _referencias_por_chave(self) -> dict[tuple[str, int], list[tuple[ReferenciaCasa, np.ndarray]]]:
        if self._referencias_sujas:
            self.referencias_automaticas = self._criar_referencias_automaticas()
            self._referencias_sujas = False
        agrupadas: dict[tuple[str, int], list[tuple[ReferenciaCasa, np.ndarray]]] = {}
        for referencia in [*self.referencias_automaticas, *self.referencias_manuais]:
            descritor = _descritor_casa(referencia.imagem, self.fundos.get(referencia.paridade))
            agrupadas.setdefault((referencia.classe, referencia.paridade), []).append(
                (referencia, descritor)
            )
        return agrupadas

    @staticmethod
    def _limiar_adaptativo(referencias: Sequence[tuple[ReferenciaCasa, np.ndarray]]) -> float:
        if len(referencias) < 3:
            return 1.1
        vizinhas: list[float] = []
        for indice, (_referencia, descritor) in enumerate(referencias):
            outras = [
                _similaridade(descritor, outro)
                for outro_indice, (_item, outro) in enumerate(referencias)
                if outro_indice != indice
            ]
            if outras:
                vizinhas.append(max(outras))
        return max(0.72, min(0.95, float(np.percentile(vizinhas, 10)) - 0.03))

    def revisar(self) -> list[ResultadoReconhecimento]:
        referencias = self._referencias_por_chave()
        revisados: list[ResultadoReconhecimento] = []
        for indice_diagrama, resultado in enumerate(self.resultados_originais):
            classes = _classes_modelo_da_posicao(resultado.posicao_original_padrao)
            alteracoes: list[AlteracaoAutomatica] = []
            duvidas: list[DuvidaAutomatica] = []
            if resultado.possivel_falso_positivo or indice_diagrama in self.excluidos:
                revisados.append(resultado)
                continue
            for casa in resultado.casas:
                original = classes[casa.indice]
                pares_conhecidos = any(
                    frozenset((original, alternativa)) in PARES_CONFUSAO
                    for alternativa in casa.top3
                    if alternativa != original
                )
                if (
                    casa.confianca >= LIMIAR_AMBIGUIDADE
                    and casa.margem >= MARGEM_AMBIGUIDADE
                    and not pares_conhecidos
                ):
                    continue
                descritor = _descritor_casa(casa.imagem, self.fundos.get(casa.paridade))
                refs_original = referencias.get((original, casa.paridade), [])
                if len(refs_original) < 3:
                    alternativa_conhecida = next(
                        (
                            alternativa
                            for alternativa in casa.top3
                            if alternativa != original
                            and frozenset((original, alternativa)) in PARES_CONFUSAO
                        ),
                        None,
                    )
                    if alternativa_conhecida is not None:
                        duvidas.append(
                            DuvidaAutomatica(
                                casa.indice,
                                casa.coordenada,
                                original,
                                alternativa_conhecida,
                                0.0,
                            )
                        )
                    continue
                sims_original = sorted(
                    (_similaridade(descritor, ref_desc) for _ref, ref_desc in refs_original),
                    reverse=True,
                )
                sim_original = float(np.mean(sims_original[:3]))
                melhor: tuple[str, float, float] | None = None
                for alternativa in casa.top3:
                    if alternativa == original:
                        continue
                    refs_alternativa = referencias.get((alternativa, casa.paridade), [])
                    if len(refs_alternativa) < 3:
                        continue
                    todas = [
                        (classe, _similaridade(descritor, ref_desc))
                        for classe in (original, alternativa)
                        for _ref, ref_desc in referencias.get((classe, casa.paridade), [])
                    ]
                    tres_vizinhas = sorted(todas, key=lambda item: item[1], reverse=True)[:3]
                    if len(tres_vizinhas) < 3 or any(classe != alternativa for classe, _sim in tres_vizinhas):
                        continue
                    sims_alternativa = sorted(
                        (_similaridade(descritor, ref_desc) for _ref, ref_desc in refs_alternativa),
                        reverse=True,
                    )
                    sim_alternativa = float(np.mean(sims_alternativa[:3]))
                    if sim_alternativa < self._limiar_adaptativo(refs_alternativa):
                        continue
                    indice_original = ALFABETO_MODELO.index(original)
                    indice_alternativa = ALFABETO_MODELO.index(alternativa)
                    score_original = 0.45 * float(casa.probabilidades[indice_original]) + 0.55 * sim_original
                    score_alternativa = 0.45 * float(casa.probabilidades[indice_alternativa]) + 0.55 * sim_alternativa
                    vantagem = score_alternativa - score_original
                    if melhor is None or vantagem > melhor[2]:
                        melhor = (alternativa, sim_alternativa, vantagem)
                if melhor is None:
                    alternativa_conhecida = next(
                        (
                            alternativa
                            for alternativa in casa.top3
                            if alternativa != original
                            and frozenset((original, alternativa)) in PARES_CONFUSAO
                        ),
                        None,
                    )
                    if alternativa_conhecida is not None:
                        duvidas.append(
                            DuvidaAutomatica(
                                casa.indice,
                                casa.coordenada,
                                original,
                                alternativa_conhecida,
                                0.0,
                            )
                        )
                    continue
                alternativa, similaridade, vantagem = melhor
                if vantagem < VANTAGEM_MINIMA_REVISAO:
                    if vantagem > 0:
                        duvidas.append(
                            DuvidaAutomatica(
                                casa.indice,
                                casa.coordenada,
                                original,
                                alternativa,
                                similaridade,
                            )
                        )
                    continue
                propostas = classes.copy()
                propostas[casa.indice] = alternativa
                if _penalidade_plausibilidade(propostas) > _penalidade_plausibilidade(classes):
                    continue
                classes = propostas
                alteracoes.append(
                    AlteracaoAutomatica(
                        casa.indice,
                        casa.coordenada,
                        original,
                        alternativa,
                        casa.confianca,
                        similaridade,
                        vantagem,
                    )
                )
            posicao_padrao = _compactar_classes(classes)
            posicao_convertida = converter_padrao_para_idioma(posicao_padrao, self.idioma)
            aviso = resultado.aviso
            if alteracoes:
                aviso = (aviso + " " if aviso else "") + (
                    f"{len(alteracoes)} casa(s) revisada(s) por comparação com o próprio livro."
                )
            if duvidas:
                aviso = (aviso + " " if aviso else "") + (
                    f"{len(duvidas)} casa(s) permaneceram ambíguas."
                )
            revisados.append(
                replace(
                    resultado,
                    posicao=posicao_convertida,
                    aviso=aviso,
                    alteracoes_automaticas=tuple(alteracoes),
                    duvidas_automaticas=tuple(duvidas),
                    confiavel=resultado.confiavel and not duvidas,
                )
            )
        return revisados


@dataclass
class ItemRevisao:
    posicao: str = ""
    confirmada: bool = False
    girado: bool = False
    confianca_minima: float = 0.0
    confiavel: bool = False
    aviso: str = ""
    nao_e_tabuleiro: bool = False
    posicao_original: str = ""
    alteracoes_automaticas: tuple[AlteracaoAutomatica, ...] = ()
    duvidas_automaticas: tuple[DuvidaAutomatica, ...] = ()
    editada_manualmente: bool = False
    casas: tuple[DadosCasa, ...] = ()

    @classmethod
    def de_reconhecimento(cls, resultado: ResultadoReconhecimento) -> "ItemRevisao":
        return cls(
            posicao=resultado.posicao,
            confirmada=False,
            girado=resultado.girado,
            confianca_minima=resultado.confianca_minima,
            confiavel=resultado.confiavel,
            aviso=resultado.aviso,
            posicao_original=resultado.posicao,
            alteracoes_automaticas=resultado.alteracoes_automaticas,
            duvidas_automaticas=resultado.duvidas_automaticas,
            casas=resultado.casas,
        )


def _impressao_digital_pdf(caminho_pdf: os.PathLike[str] | str) -> str:
    caminho = Path(caminho_pdf).expanduser().resolve()
    estado = caminho.stat()
    origem = f"{caminho}|{estado.st_size}|{estado.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(origem).hexdigest()


def caminho_rascunho(caminho_pdf: os.PathLike[str] | str, pasta: Path) -> Path:
    return pasta / "drafts" / f"{_impressao_digital_pdf(caminho_pdf)}.json"


def caminho_referencias_manuais(caminho_pdf: os.PathLike[str] | str, pasta: Path) -> Path:
    return pasta / "learning" / f"{_impressao_digital_pdf(caminho_pdf)}.json"


def salvar_referencias_manuais(
    caminho_pdf: os.PathLike[str] | str,
    referencias: Sequence[ReferenciaCasa],
    pasta: Path,
) -> Path:
    destino = caminho_referencias_manuais(caminho_pdf, pasta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    itens: list[dict[str, object]] = []
    for referencia in referencias:
        imagem = np.clip(referencia.imagem * 255.0, 0, 255).astype(np.uint8)
        sucesso, buffer = cv2.imencode(".png", imagem)
        if not sucesso:
            continue
        itens.append(
            {
                "classe": referencia.classe,
                "paridade": referencia.paridade,
                "origem_diagrama": referencia.origem_diagrama,
                "imagem_png": base64.b64encode(buffer.tobytes()).decode("ascii"),
            }
        )
    conteudo = {
        "schema": 1,
        "origem": _impressao_digital_pdf(caminho_pdf),
        "itens": itens,
    }
    temporario = destino.with_suffix(".json.tmp")
    temporario.write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
    os.replace(temporario, destino)
    return destino


def carregar_referencias_manuais(
    caminho_pdf: os.PathLike[str] | str,
    pasta: Path,
) -> list[ReferenciaCasa]:
    arquivo = caminho_referencias_manuais(caminho_pdf, pasta)
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if dados.get("schema") != 1 or dados.get("origem") != _impressao_digital_pdf(caminho_pdf):
        return []
    referencias: list[ReferenciaCasa] = []
    for item in dados.get("itens", []):
        if not isinstance(item, dict):
            continue
        classe = item.get("classe")
        paridade = item.get("paridade")
        imagem_base64 = item.get("imagem_png")
        if classe not in ALFABETO_MODELO or paridade not in (0, 1) or not isinstance(imagem_base64, str):
            continue
        try:
            matriz = np.frombuffer(base64.b64decode(imagem_base64), dtype=np.uint8)
            imagem = cv2.imdecode(matriz, cv2.IMREAD_GRAYSCALE)
        except (ValueError, TypeError):
            continue
        if imagem is None:
            continue
        referencias.append(
            ReferenciaCasa(
                str(classe),
                int(paridade),
                cv2.resize(imagem, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0,
                int(item.get("origem_diagrama", -1)),
                manual=True,
            )
        )
    return referencias


def salvar_rascunho(
    caminho_pdf: os.PathLike[str] | str,
    itens: Sequence[ItemRevisao],
    pasta: Path,
    idioma: str = "pt",
) -> Path:
    destino = caminho_rascunho(caminho_pdf, pasta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "schema": 2,
        "origem": _impressao_digital_pdf(caminho_pdf),
        "quantidade": len(itens),
        "idioma": idioma,
        "itens": [
            {
                "posicao": item.posicao,
                "confirmada": item.confirmada,
                "girado": item.girado,
                "nao_e_tabuleiro": item.nao_e_tabuleiro,
                "posicao_original": item.posicao_original,
                "editada_manualmente": item.editada_manualmente,
                "alteracoes_automaticas": [
                    {
                        "indice": alteracao.indice,
                        "coordenada": alteracao.coordenada,
                        "original": alteracao.original,
                        "nova": alteracao.nova,
                        "confianca_modelo": alteracao.confianca_modelo,
                        "similaridade": alteracao.similaridade,
                        "vantagem": alteracao.vantagem,
                    }
                    for alteracao in item.alteracoes_automaticas
                ],
                "duvidas_automaticas": [
                    {
                        "indice": duvida.indice,
                        "coordenada": duvida.coordenada,
                        "original": duvida.original,
                        "alternativa": duvida.alternativa,
                        "similaridade": duvida.similaridade,
                    }
                    for duvida in item.duvidas_automaticas
                ],
            }
            for item in itens
        ],
    }
    temporario = destino.with_suffix(".json.tmp")
    temporario.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporario, destino)
    return destino


def carregar_rascunho(
    caminho_pdf: os.PathLike[str] | str,
    quantidade: int,
    pasta: Path,
    idioma: str = "pt",
) -> list[dict[str, object]] | None:
    arquivo = caminho_rascunho(caminho_pdf, pasta)
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if (
        dados.get("schema") not in (1, 2)
        or dados.get("origem") != _impressao_digital_pdf(caminho_pdf)
        or dados.get("idioma", "pt") != idioma
    ):
        return None
    itens = dados.get("itens")
    if dados.get("quantidade") != quantidade or not isinstance(itens, list) or len(itens) != quantidade:
        return None
    if not all(isinstance(item, dict) for item in itens):
        return None
    return itens


def aplicar_rascunho(itens: Sequence[ItemRevisao], dados: Sequence[dict[str, object]]) -> None:
    if len(itens) != len(dados):
        return
    for item, salvo in zip(itens, dados):
        posicao = salvo.get("posicao")
        if isinstance(posicao, str):
            item.posicao = posicao
        item.confirmada = bool(salvo.get("confirmada", False))
        item.girado = bool(salvo.get("girado", item.girado))
        item.nao_e_tabuleiro = bool(salvo.get("nao_e_tabuleiro", False))
        item.editada_manualmente = bool(salvo.get("editada_manualmente", False))
        posicao_original = salvo.get("posicao_original")
        if isinstance(posicao_original, str):
            item.posicao_original = posicao_original
        alteracoes = salvo.get("alteracoes_automaticas", [])
        if isinstance(alteracoes, list):
            try:
                item.alteracoes_automaticas = tuple(
                    AlteracaoAutomatica(**alteracao)
                    for alteracao in alteracoes
                    if isinstance(alteracao, dict)
                )
            except TypeError:
                item.alteracoes_automaticas = ()
        duvidas = salvo.get("duvidas_automaticas", [])
        if isinstance(duvidas, list):
            try:
                item.duvidas_automaticas = tuple(
                    DuvidaAutomatica(**duvida)
                    for duvida in duvidas
                    if isinstance(duvida, dict)
                )
            except TypeError:
                item.duvidas_automaticas = ()


def remover_rascunho(caminho_pdf: os.PathLike[str] | str, pasta: Path) -> None:
    try:
        caminho_rascunho(caminho_pdf, pasta).unlink(missing_ok=True)
    except OSError:
        pass
