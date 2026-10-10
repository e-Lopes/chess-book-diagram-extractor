"""Compara cada modelo e o ensemble em imagens com posicionamento conhecido.

python tools/avaliar_ensemble.py --manifest tests/fixtures/fenshot/posicoes.json
O manifesto deve conter arquivo (relativo ao manifesto) e posicao (FEN inglês,
apenas posicionamento, na orientação mostrada na imagem).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from extrair_tabuleiros_pdf import detectar_tabuleiros
from notacao_forsyth import ReconhecedorForsyth, _preparar_casas, _classes_modelo_da_posicao
from reconhecimento_ensemble import (
    CLASSES, ModeloONNX, ConfiguracaoModelo, carregar_catalogo,
    preparar_casas_pillow, temperar_probabilidades,
)


class AvaliadorModelo(ReconhecedorForsyth):
    """Usa a mesma busca de alinhamento e os mesmos critérios do aplicativo."""
    def __init__(self, configuracao: ConfiguracaoModelo) -> None:
        self.idioma = "en"
        self.modelo = ModeloONNX(configuracao, RAIZ / "models")
        self._configuracoes = (configuracao,)

    def _prever_ensemble(self, imagem, inset, casas_principais):
        configuracao = self.modelo.configuracao
        casas = (casas_principais if configuracao.preprocessamento == "cv2_gray"
                 else preparar_casas_pillow(imagem, inset, configuracao.preprocessamento))
        matriz = temperar_probabilidades(self.modelo.prever(casas), configuracao.temperatura)
        return matriz, (matriz,)


def avaliar(manifesto: Path) -> dict:
    exemplos = json.loads(manifesto.read_text(encoding="utf-8"))
    configuracoes = carregar_catalogo(RAIZ / "models/ensemble.json")
    reconhecedores = {cfg.nome: AvaliadorModelo(cfg) for cfg in configuracoes}
    reconhecedores["ensemble"] = ReconhecedorForsyth(idioma="en")
    relatorio = {
        "manifesto": str(manifesto),
        "pesos": {c.nome: c.peso for c in configuracoes},
        "temperaturas": {c.nome: c.temperatura for c in configuracoes},
        "sha256": {c.nome: c.sha256 for c in configuracoes},
        "modelos": {},
    }
    for nome in reconhecedores:
        relatorio["modelos"][nome] = {
            "diagramas": 0, "posicoes_exatas": 0, "casas": 0, "casas_corretas": 0,
            "casas_ocupadas": 0, "casas_ocupadas_corretas": 0,
            "posicoes_confiaveis": 0, "posicoes_incorretas_confiaveis": 0,
            "matriz_confusao": np.zeros((13, 13), np.int64), "segundos": 0.0, "exemplos": [],
        }
    for exemplo in exemplos:
        arquivo = manifesto.parent / exemplo["arquivo"]
        imagem = cv2.imread(str(arquivo))
        if imagem is None:
            raise ValueError(f"Imagem inválida: {arquivo}")
        candidatos = detectar_tabuleiros(imagem, aceitar_quadrados=False)
        if len(candidatos) != 1:
            raise ValueError(f"Esperado um tabuleiro por imagem de avaliação: {arquivo}")
        esperadas = _classes_modelo_da_posicao(exemplo["posicao"])
        for nome, reconhecedor in reconhecedores.items():
            inicio = time.perf_counter()
            resultado = reconhecedor.reconhecer(candidatos[0].imagem)
            duracao = time.perf_counter() - inicio
            previstas = _classes_modelo_da_posicao(resultado.posicao)
            erros = []
            dados = relatorio["modelos"][nome]
            for indice, (esperada, prevista) in enumerate(zip(esperadas, previstas)):
                dados["matriz_confusao"][CLASSES.index(esperada), CLASSES.index(prevista)] += 1
                dados["casas_corretas"] += int(esperada == prevista)
                dados["casas_ocupadas"] += int(esperada != "1")
                dados["casas_ocupadas_corretas"] += int(esperada != "1" and esperada == prevista)
                if esperada != prevista:
                    erros.append({"casa": resultado.casas[indice].coordenada, "esperada": esperada, "prevista": prevista})
            dados["diagramas"] += 1
            dados["casas"] += 64
            dados["posicoes_exatas"] += int(not erros)
            dados["posicoes_confiaveis"] += int(resultado.confiavel)
            dados["posicoes_incorretas_confiaveis"] += int(bool(erros) and resultado.confiavel)
            dados["segundos"] += duracao
            dados["exemplos"].append({
                "arquivo": exemplo["arquivo"], "posicao": resultado.posicao, "erros": erros,
                "confiavel": resultado.confiavel,
                "casas_divergentes": [c.coordenada for c in resultado.casas if c.divergencia_modelos],
                "segundos": duracao,
            })
    for nome, dados in relatorio["modelos"].items():
        dados["matriz_confusao"] = dados["matriz_confusao"].tolist()
        print(f"{nome}: {dados['posicoes_exatas']}/{dados['diagramas']} posições exatas; "
              f"{dados['casas_corretas']}/{dados['casas']} casas; "
              f"{dados['posicoes_incorretas_confiaveis']} posições erradas marcadas confiáveis")
    return relatorio


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=RAIZ / "tests/fixtures/fenshot/posicoes.json")
    parser.add_argument("--saida", type=Path, default=RAIZ / "build/avaliacao-ensemble.json")
    args = parser.parse_args()
    relatorio = avaliar(args.manifest)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(relatorio, indent=2, ensure_ascii=False), encoding="utf-8")
