"""Contratos, pré-processamento e votação dos modelos locais de peças 2D."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np
from PIL import Image

CLASSES = "1KQRBNPkqrbnp"


@dataclass(frozen=True)
class ConfiguracaoModelo:
    nome: str
    arquivo: str
    sha256: str
    peso: float
    temperatura: float = 1.0
    preprocessamento: str = "cv2_gray"
    classes: str = CLASSES

    def __post_init__(self) -> None:
        if not self.nome or Path(self.arquivo).name != self.arquivo:
            raise ValueError("O modelo precisa de nome e arquivo dentro da pasta models.")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256.lower()):
            raise ValueError("SHA-256 do modelo inválido.")
        if not np.isfinite(self.peso) or self.peso <= 0:
            raise ValueError("O peso do modelo precisa ser positivo e finito.")
        if not np.isfinite(self.temperatura) or self.temperatura <= 0:
            raise ValueError("A temperatura precisa ser positiva e finita.")
        if len(self.classes) != 13 or set(self.classes) != set(CLASSES):
            raise ValueError("O modelo precisa representar as mesmas 13 classes, sem repetições.")
        if self.preprocessamento not in ("cv2_gray", "pillow_gray", "pillow_rgb_gray"):
            raise ValueError("Pré-processamento de modelo desconhecido.")


@dataclass(frozen=True)
class PrevisaoModelo:
    nome: str
    classe: str
    confianca: float
    probabilidades: tuple[float, ...]


def carregar_catalogo(caminho: Path) -> tuple[ConfiguracaoModelo, ...]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if dados.get("versao") != 1 or not isinstance(dados.get("modelos"), list):
        raise ValueError("Catálogo de modelos inválido.")
    modelos = tuple(ConfiguracaoModelo(**item) for item in dados["modelos"])
    if not modelos or len({m.nome for m in modelos}) != len(modelos):
        raise ValueError("O catálogo precisa de modelos com nomes únicos.")
    # Cópias dos mesmos pesos não são membros independentes do ensemble.
    if len({m.sha256.lower() for m in modelos}) != len(modelos):
        raise ValueError("O catálogo contém cópias do mesmo modelo.")
    return modelos


def validar_probabilidades(probabilidades: np.ndarray) -> np.ndarray:
    matriz = np.asarray(probabilidades, dtype=np.float32)
    if matriz.shape != (64, 13):
        raise ValueError("O modelo precisa retornar 64 casas com 13 probabilidades cada.")
    if not np.isfinite(matriz).all() or (matriz < 0).any() or (matriz > 1).any():
        raise ValueError("O modelo retornou probabilidades inválidas.")
    if not np.allclose(matriz.sum(axis=1), 1.0, atol=1e-4):
        raise ValueError("As probabilidades de cada casa precisam somar 1.")
    return matriz


def temperar_probabilidades(probabilidades: np.ndarray, temperatura: float) -> np.ndarray:
    matriz = validar_probabilidades(probabilidades)
    if not np.isfinite(temperatura) or temperatura <= 0:
        raise ValueError("A temperatura precisa ser positiva e finita.")
    if temperatura == 1.0:
        return matriz.copy()
    # Preserva zeros verdadeiros e usa logs para evitar overflow/underflow.
    with np.errstate(divide="ignore"):
        logp = np.log(matriz.astype(np.float64)) / temperatura
    logp -= logp.max(axis=1, keepdims=True)
    ajustada = np.exp(logp)
    return (ajustada / ajustada.sum(axis=1, keepdims=True)).astype(np.float32)


def combinar_probabilidades(matrizes: Sequence[np.ndarray], pesos: Sequence[float]) -> np.ndarray:
    if not matrizes or len(matrizes) != len(pesos):
        raise ValueError("Cada modelo precisa de uma matriz e um peso.")
    ponderacao = np.asarray(pesos, dtype=np.float64)
    if not np.isfinite(ponderacao).all() or (ponderacao <= 0).any():
        raise ValueError("Os pesos precisam ser positivos e finitos.")
    ponderacao /= ponderacao.sum()
    matrizes_validas = np.stack([validar_probabilidades(m) for m in matrizes])
    resultado = np.tensordot(ponderacao, matrizes_validas, axes=(0, 0)).astype(np.float32)
    resultado /= resultado.sum(axis=1, keepdims=True)
    return validar_probabilidades(resultado)


def preparar_casas_pillow(imagem: np.ndarray, inset: float, preprocessamento: str) -> np.ndarray:
    if (not isinstance(imagem, np.ndarray) or imagem.dtype != np.uint8
            or imagem.ndim not in (2, 3) or min(imagem.shape[:2]) < 8
            or (imagem.ndim == 3 and imagem.shape[2] not in (3, 4))):
        raise ValueError("Imagem inválida para reconhecimento.")
    if not 0 <= inset < 0.5:
        raise ValueError("Recuo inválido.")
    altura, largura = imagem.shape[:2]
    margem = int(round(min(altura, largura) * inset))
    recorte = imagem[margem:altura-margem, margem:largura-margem] if margem else imagem
    if recorte.ndim == 3:
        rgb = cv2.cvtColor(recorte, cv2.COLOR_BGR2RGB if recorte.shape[2] == 3 else cv2.COLOR_BGRA2RGB)
        original = Image.fromarray(rgb)
    else:
        original = Image.fromarray(recorte)
    if preprocessamento == "pillow_gray":
        tabuleiro = original.convert("L").resize((256, 256), Image.Resampling.BILINEAR)
    elif preprocessamento == "pillow_rgb_gray":
        tabuleiro = original.convert("RGB").resize((256, 256), Image.Resampling.BILINEAR)
        tabuleiro = tabuleiro.convert("L", (0.2989, 0.5870, 0.1140, 0))
    else:
        raise ValueError("Pré-processamento Pillow desconhecido.")
    pixels = np.asarray(tabuleiro, dtype=np.float32) / 255.0
    casas = pixels.reshape(8, 32, 8, 32).transpose(0, 2, 1, 3)[::-1]
    return np.ascontiguousarray(casas.reshape(64, 1024))


class ModeloONNX:
    def __init__(self, configuracao: ConfiguracaoModelo, pasta: Path) -> None:
        import onnxruntime as ort
        self.configuracao = configuracao
        caminho = pasta / configuracao.arquivo
        if not caminho.is_file():
            raise FileNotFoundError(f"Modelo do ensemble não encontrado: {caminho}")
        if hashlib.sha256(caminho.read_bytes()).hexdigest() != configuracao.sha256.lower():
            raise RuntimeError(f"O modelo {configuracao.nome} falhou na validação SHA-256.")
        opcoes = ort.SessionOptions()
        opcoes.intra_op_num_threads = 2
        opcoes.inter_op_num_threads = 1
        self.sessao = ort.InferenceSession(str(caminho), sess_options=opcoes, providers=["CPUExecutionProvider"])
        entradas, saidas = self.sessao.get_inputs(), self.sessao.get_outputs()
        if (len(entradas) != 1 or len(saidas) != 1 or entradas[0].type != "tensor(float)"
                or len(entradas[0].shape) != 2 or entradas[0].shape[1] != 1024
                or len(saidas[0].shape) != 2 or saidas[0].shape[1] != 13):
            raise ValueError(f"Contrato ONNX incompatível no modelo {configuracao.nome}.")
        self.entrada, self.saida = entradas[0].name, saidas[0].name

    def prever(self, casas: np.ndarray) -> np.ndarray:
        probabilidades = self.sessao.run([self.saida], {self.entrada: casas})[0]
        matriz = validar_probabilidades(probabilidades)
        ordem = [self.configuracao.classes.index(c) for c in CLASSES]
        return matriz[:, ordem].copy()
