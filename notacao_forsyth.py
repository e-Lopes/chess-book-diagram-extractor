"""Reconhecimento e revisão da posição das peças em notação Forsyth portuguesa."""

from __future__ import annotations

from marcadores_diagrama import casas_com_bolinhas

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
from alinhamento_tabuleiro import alinhar_grade
from restricoes_reconhecimento import eleger_com_reis

from reconhecimento_ensemble import (
    ConfiguracaoModelo, ModeloONNX, PrevisaoModelo, carregar_catalogo,
    combinar_probabilidades, preparar_casas_pillow, temperar_probabilidades,
    validar_probabilidades as _validar_probabilidades,
)


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


def separar_posicao_lado(texto: str, lado_padrao: str = "w") -> tuple[str, str]:
    """Separa a posição do sufixo opcional ``w``/``b`` usado na interface."""
    if lado_padrao not in ("w", "b"):
        lado_padrao = "w"
    normalizado = " ".join(texto.strip().split())
    partes = normalizado.rsplit(maxsplit=1)
    if len(partes) == 2 and partes[1].lower() in ("w", "b"):
        return partes[0], partes[1].lower()
    return normalizado, lado_padrao


def formatar_posicao_lado(posicao: str, lado_a_jogar: str) -> str:
    lado = lado_a_jogar if lado_a_jogar in ("w", "b") else "w"
    posicao = " ".join(posicao.strip().split())
    return f"{posicao} {lado}" if posicao else lado


def substituir_casa(texto: str, linha: int, coluna: int, peca: str, idioma: str = "pt") -> str:
    """Edita uma casa visual (a8 = 0,0), preservando lado e campos FEN.

    Colocar um rei move o rei da mesma cor, sem criar outro. Durante uma
    correção pode faltar um rei; a validação existente impede exportá-la assim.
    """
    if not 0 <= linha < 8 or not 0 <= coluna < 8:
        raise ValueError("Casa fora do tabuleiro.")
    pecas = pecas_do_idioma(idioma)
    if peca and peca not in pecas:
        raise ValueError("Peça inválida.")
    campos = texto.strip().split()
    if not campos or len(campos) not in (1, 2, 6) or (len(campos) > 1 and campos[1] not in ("w", "b")):
        raise ValueError("Posição inválida para edição.")
    tabuleiro = expandir_posicao(campos[0], pecas)
    reis = "Rr" if idioma == "pt" else "Kk"
    if peca in reis and peca:
        for casas in tabuleiro:
            for indice, atual in enumerate(casas):
                if atual == peca:
                    casas[indice] = ""
    tabuleiro[linha][coluna] = peca
    return " ".join([compactar_tabuleiro(tabuleiro), *campos[1:]])


def validar_posicao(posicao: str, idioma: str = "pt") -> tuple[bool, str]:
    if not posicao.strip():
        return False, "Informe a posição das peças."
    try:
        normalizada = normalizar_posicao(posicao, idioma)
    except ValueError as erro:
        return False, str(erro)
    rei_branco, rei_preto = ("R", "r") if idioma == "pt" else ("K", "k")
    quantidade_brancos = normalizada.count(rei_branco)
    quantidade_pretos = normalizada.count(rei_preto)
    if quantidade_brancos == 0:
        return False, "A posição precisa conter um rei branco."
    if quantidade_brancos > 1:
        return False, "A posição não pode conter mais de um rei branco."
    if quantidade_pretos == 0:
        return False, "A posição precisa conter um rei preto."
    if quantidade_pretos > 1:
        return False, "A posição não pode conter mais de um rei preto."
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


def _decodificar_probabilidades(
    probabilidades: np.ndarray,
) -> tuple[str, list[float], float, float, np.ndarray]:
    matriz = _validar_probabilidades(probabilidades)
    indices = np.argmax(matriz, axis=1)
    # A fileira da peça não comprova sua identidade. Confusões são revistas
    # somente com evidência visual do livro, em RevisorAutomaticoLivro.
    confiancas = matriz[np.arange(64), indices].astype(float).tolist()
    classes = [ALFABETO_MODELO[indice] for indice in indices]
    posicao = _compactar_classes(classes)
    return (
        posicao,
        confiancas,
        min(confiancas),
        sum(confiancas) / len(confiancas),
        indices.copy(),
    )


def decodificar_probabilidades(probabilidades: np.ndarray) -> tuple[str, list[float], float, float]:
    posicao, confiancas, minima, media, _indices = _decodificar_probabilidades(probabilidades)
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
    if (not isinstance(imagem, np.ndarray) or imagem.dtype != np.uint8
            or imagem.ndim not in (2, 3) or min(imagem.shape[:2]) < 8
            or (imagem.ndim == 3 and imagem.shape[2] not in (3, 4))):
        raise ValueError("Informe uma imagem uint8 em cinza, BGR ou BGRA com pelo menos 8×8 pixels.")
    if not 0 <= inset < 0.5:
        raise ValueError("O recuo das bordas precisa estar entre 0 e 0,5.")
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
    previsoes_modelos: tuple[PrevisaoModelo, ...] = ()
    concordancia: float = 1.0
    divergencia_modelos: bool = False
    marcador_vazio: bool = False


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
    ajustes_reis: tuple[str, ...] = ()
    limites_grade: tuple[int, int, int, int] = ()


class ReconhecedorForsyth:
    def __init__(
        self,
        caminho_modelo: os.PathLike[str] | str | None = None,
        idioma: str = "pt",
        usar_ensemble: bool = True,
        caminho_catalogo: os.PathLike[str] | str | None = None,
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
        opcoes = ort.SessionOptions()
        opcoes.intra_op_num_threads = 2
        opcoes.inter_op_num_threads = 1
        self._sessao = ort.InferenceSession(str(self.caminho_modelo), sess_options=opcoes, providers=["CPUExecutionProvider"])
        self._entrada = self._sessao.get_inputs()[0].name
        self._saida = self._sessao.get_outputs()[0].name
        self._configuracoes = (ConfiguracaoModelo("fenshot", NOME_MODELO, SHA256_MODELO, 1.0),)
        self._modelos_adicionais: tuple[ModeloONNX, ...] = ()
        if usar_ensemble and caminho_modelo is None:
            catalogo = Path(caminho_catalogo) if caminho_catalogo else caminho_recurso("models", "ensemble.json")
            configuracoes = carregar_catalogo(catalogo)
            principal = configuracoes[0]
            if (principal.nome != "fenshot" or principal.arquivo != NOME_MODELO
                    or principal.sha256.upper() != SHA256_MODELO
                    or principal.preprocessamento != "cv2_gray" or principal.classes != ALFABETO_MODELO):
                raise ValueError("O primeiro modelo do catálogo precisa ser o fenshot incluído no aplicativo.")
            self._modelos_adicionais = tuple(ModeloONNX(c, catalogo.parent) for c in configuracoes[1:])
            self._configuracoes = configuracoes

    def _prever_ensemble(
        self, imagem: np.ndarray, inset: float, casas_principais: np.ndarray,
    ) -> tuple[np.ndarray, tuple[np.ndarray, ...]]:
        principal = _validar_probabilidades(self._sessao.run([self._saida], {self._entrada: casas_principais})[0])
        configuracoes = getattr(self, "_configuracoes", ())
        adicionais = getattr(self, "_modelos_adicionais", ())
        temperatura = configuracoes[0].temperatura if configuracoes else 1.0
        matrizes = [temperar_probabilidades(principal, temperatura)]
        for modelo in adicionais:
            preparo = modelo.configuracao.preprocessamento
            casas = (casas_principais if preparo == "cv2_gray"
                     else preparar_casas_pillow(imagem, inset, preparo))
            matriz = modelo.prever(casas)
            matrizes.append(temperar_probabilidades(matriz, modelo.configuracao.temperatura))
        pesos = [c.peso for c in configuracoes] if configuracoes else [1.0]
        return combinar_probabilidades(matrizes, pesos), tuple(matrizes)

    def reconhecer(self, imagem: np.ndarray) -> ResultadoReconhecimento:
        # Primeiro remove coordenadas e molduras assimétricas; somente depois
        # testa os pequenos recuos destinados às linhas externas da grade.
        imagem, limites_grade = alinhar_grade(imagem)
        marcadores = casas_com_bolinhas(imagem)
        melhor: tuple[
            tuple[str, list[float], float, float, np.ndarray],
            np.ndarray,
            np.ndarray,
            tuple[np.ndarray, ...],
        ] | None = None
        melhor_score = -float("inf")
        for inset in (0.0, 0.005, 0.01, 0.02, 0.03, 0.045):
            casas = _preparar_casas(imagem, inset)
            probabilidades, previsoes = self._prever_ensemble(imagem, inset, casas)
            eleicao = probabilidades.copy()
            if marcadores:
                eleicao[list(marcadores)] = 0
                eleicao[list(marcadores), 0] = 1
            atual = _decodificar_probabilidades(eleicao)
            matriz = _validar_probabilidades(probabilidades)
            confiancas = np.asarray(atual[1])
            ocupadas = atual[4] != 0
            confianca_pecas = float(confiancas[ocupadas].mean()) if ocupadas.any() else atual[3]
            # Casas vazias não devem esconder peças mal alinhadas em finais
            # esparsos. As oito casas menos seguras também pesam na seleção.
            score = (0.5 * atual[3] + 0.25 * confianca_pecas
                     + 0.25 * float(np.sort(confiancas)[:8].mean())
                     - 0.02 * _penalidade_plausibilidade(_classes_modelo_da_posicao(atual[0])))
            if score > melhor_score:
                melhor_score = score
                melhor = (atual, casas.copy(), matriz.copy(), previsoes)
        assert melhor is not None
        decodificado, imagens_casas, matriz_probabilidades, previsoes = melhor
        posicao_padrao, _confiancas, minima, media, indices = decodificado
        eleicao = matriz_probabilidades.copy()
        if marcadores:
            eleicao[list(marcadores)] = 0
            eleicao[list(marcadores), 0] = 1
        indices, casas_ajustadas = eleger_com_reis(eleicao, casas_vazias=marcadores)
        posicao_padrao = _compactar_classes([ALFABETO_MODELO[int(i)] for i in indices])
        confiancas_escolhidas = matriz_probabilidades[np.arange(64), indices]
        sem_marcadores = np.ones(64, dtype=bool)
        sem_marcadores[list(marcadores)] = False
        confiancas_pecas = confiancas_escolhidas[sem_marcadores]
        minima = float(confiancas_pecas.min()) if confiancas_pecas.size else 0.0
        media = float(confiancas_pecas.mean()) if confiancas_pecas.size else 0.0
        dados_casas: list[DadosCasa] = []
        configuracoes = getattr(self, "_configuracoes", ())
        pesos = np.array([c.peso for c in configuracoes] if configuracoes else [1.0], np.float64)
        pesos /= pesos.sum()
        for indice_casa in range(64):
            ordem = np.argsort(matriz_probabilidades[indice_casa])[::-1]
            coluna = indice_casa % 8
            linha_modelo = indice_casa // 8
            votos = tuple(
                PrevisaoModelo(
                    nome=configuracoes[i].nome if configuracoes else "fenshot",
                    classe=ALFABETO_MODELO[int(np.argmax(m[indice_casa]))],
                    confianca=float(np.max(m[indice_casa])),
                    probabilidades=tuple(float(p) for p in m[indice_casa]),
                )
                for i, m in enumerate(previsoes)
            )
            eleita = ALFABETO_MODELO[int(indices[indice_casa])]
            concordancia = sum(float(peso) for voto, peso in zip(votos, pesos) if voto.classe == eleita)
            divergencia = (concordancia < 0.75 or any(
                voto.classe != eleita and voto.confianca >= LIMIAR_CONFIANCA for voto in votos
            )) if len(votos) > 1 else False
            dados_casas.append(
                DadosCasa(
                    indice=indice_casa,
                    coordenada=f"{chr(ord('a') + coluna)}{linha_modelo + 1}",
                    paridade=paridade_casa_modelo(indice_casa),
                    imagem=imagens_casas[indice_casa].reshape(32, 32).copy(),
                    probabilidades=matriz_probabilidades[indice_casa].copy(),
                    classe_original=ALFABETO_MODELO[int(np.argmax(matriz_probabilidades[indice_casa]))],
                    top3=tuple(ALFABETO_MODELO[int(item)] for item in ordem[:3]),
                    confianca=float(matriz_probabilidades[indice_casa, indices[indice_casa]]),
                    margem=float(
                        matriz_probabilidades[indice_casa, ordem[0]]
                        - matriz_probabilidades[indice_casa, ordem[1]]
                    ),
                    previsoes_modelos=votos,
                    concordancia=concordancia,
                    divergencia_modelos=divergencia,
                    marcador_vazio=indice_casa in marcadores,
                )
            )
        # Os livros processados usam orientação padronizada. A leitura mantém
        # exatamente o topo e a base mostrados no PDF de extrações.
        posicao_orientada, girado, ambigua = posicao_padrao, False, False
        posicao_convertida = converter_padrao_para_idioma(posicao_orientada, self.idioma)
        plausibilidade = aviso_plausibilidade(posicao_convertida, self.idioma)
        motivos: list[str] = []
        if marcadores:
            motivos.append("Bolinhas indicativas tratadas como casas vazias: " + ", ".join(
                f"{chr(97 + i % 8)}{i // 8 + 1}" for i in marcadores) + ".")
        ajustes_reis = tuple(f"{chr(97 + i % 8)}{i // 8 + 1}" for i in casas_ajustadas)
        if ajustes_reis:
            motivos.append("Reis ajustados pela confiança em: " + ", ".join(ajustes_reis) + ". Confira essas casas.")
        ambiguas = [casa.coordenada for casa in dados_casas
                    if not casa.marcador_vazio and (casa.confianca < LIMIAR_CONFIANCA or casa.margem < MARGEM_AMBIGUIDADE)]
        divergentes = [casa.coordenada for casa in dados_casas if casa.divergencia_modelos and not casa.marcador_vazio]
        if minima < LIMIAR_CONFIANCA:
            motivos.append("Algumas casas tiveram baixa confiança.")
        if ambiguas:
            motivos.append("Confira as casas: " + ", ".join(ambiguas) + ".")
        if divergentes:
            motivos.append("Os modelos divergiram nas casas: " + ", ".join(divergentes) + ".")
        if ambigua:
            motivos.append("A orientação não pôde ser determinada com segurança.")
        if plausibilidade:
            motivos.append(plausibilidade)
        return ResultadoReconhecimento(
            posicao=posicao_convertida,
            confianca_minima=minima,
            confianca_media=media,
            confiavel=(
                minima >= LIMIAR_CONFIANCA
                and not ambiguas
                and not divergentes
                and not ambigua
                and not plausibilidade
                and not ajustes_reis
            ),
            girado=girado,
            orientacao_ambigua=ambigua,
            aviso=" ".join(motivos),
            posicao_original_padrao=posicao_padrao,
            casas=tuple(dados_casas),
            possivel_falso_positivo=bool(plausibilidade),
            ajustes_reis=ajustes_reis,
            limites_grade=limites_grade,
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
                for indice_diagrama, resultado in enumerate(self.resultados_originais)
                if not resultado.possivel_falso_positivo and indice_diagrama not in self.excluidos
                for casa in resultado.casas
                if casa.paridade == paridade
                and casa.top3[0] == "1"
                and casa.confianca >= LIMIAR_REFERENCIA
                and casa.margem >= MARGEM_REFERENCIA
                and not casa.divergencia_modelos
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
                    casa.marcador_vazio
                    or casa.classe_original == "1"
                    or casa.classe_original != casa.top3[0]
                    or casa.confianca < LIMIAR_REFERENCIA
                    or casa.margem < MARGEM_REFERENCIA
                    or casa.divergencia_modelos
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
            # Uma nova edição da mesma imagem substitui o rótulo anterior;
            # manter os dois ensinava classes contraditórias ao revisor.
            self.referencias_manuais = [
                existente for existente in self.referencias_manuais
                if not (existente.origem_diagrama == indice_diagrama
                        and existente.paridade == casa.paridade
                        and np.array_equal(existente.imagem, casa.imagem))
            ]
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
            item.revisao_necessaria = not resultado.confiavel

    def substituir_resultado(self, indice: int, resultado: ResultadoReconhecimento) -> None:
        self.resultados_originais[indice] = resultado
        self._referencias_sujas = True

    def _referencias_por_chave(self) -> dict[tuple[str, int], list[tuple[ReferenciaCasa, np.ndarray]]]:
        if self._referencias_sujas:
            self.fundos = self._criar_fundos()
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
                if casa.marcador_vazio:
                    continue
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
                if any(propostas.count(rei) != classes.count(rei) for rei in ("K", "k")):
                    continue
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
                    confiavel=resultado.confiavel and not duvidas and not alteracoes,
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
    lado_a_jogar: str = "w"
    ajustes_reis: tuple[str, ...] = ()
    revisao_necessaria: bool = False

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
            ajustes_reis=resultado.ajustes_reis,
            revisao_necessaria=not resultado.confiavel,
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
        "schema": 3,
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
                "revisao_necessaria": item.revisao_necessaria,
                "lado_a_jogar": item.lado_a_jogar,
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
        dados.get("schema") not in (1, 2, 3)
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
        item.revisao_necessaria = bool(salvo.get("revisao_necessaria", item.revisao_necessaria))
        lado_a_jogar = salvo.get("lado_a_jogar", "w")
        item.lado_a_jogar = lado_a_jogar if lado_a_jogar in ("w", "b") else "w"
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
