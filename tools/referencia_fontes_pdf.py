"""Referência independente dos modelos, obtida de duas fontes de diagramas.

Este leitor de avaliação aceita somente grades completas com oito linhas de
oito casas, delimitadas pela moldura da fonte. Fontes desconhecidas e diagramas
rasterizados ficam fora da referência. Não utiliza previsões para escolher peças.
"""
from __future__ import annotations

import re
from pathlib import Path
import sys

import cv2
import fitz
import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from notacao_forsyth import compactar_tabuleiro


# Ponto e dois-pontos marcam uma casa vazia destacada, em fundos distintos.
MERIDA = {**dict.fromkeys(" +.:", ""), **{c: c.upper() for c in "rnbqkp"},
          **{c: c for c in "RNBQKP"},
          **{c: p for c, p in zip("tmvwloTMVWLO", "rnbqkprnbqkp")}}
FRITZ = re.compile(r"w[Qq]|t[Rr]|v[Ll]|s[Nn]|m[Kk]|z[Pp]|[KQRNLkqrnlPp+\-]")


def decodificar_linha(texto: str, fonte: str, rank: int) -> list[str]:
    if fonte == "ChessMerida":
        texto = "".join(chr(ord(c) - 0xF000) if 0xF000 <= ord(c) < 0xF100 else c for c in texto)
        if len(texto) != 10 or texto[0] != "4" or texto[-1] != "5":
            raise ValueError("Linha Merida sem moldura completa")
        try:
            return [MERIDA[c] for c in texto[1:-1]]
        except KeyError as erro:
            raise ValueError("Glifo Merida desconhecido") from erro
    if fonte == "DiagramTTFritz":
        texto = texto.rstrip()
        if not texto or texto[0] != str(rank) or texto[-1] != "!\"#$%&'("[rank - 1]:
            raise ValueError("Linha Fritz sem moldura completa")
        conteudo = texto[1:-1]
        tokens = FRITZ.findall(conteudo)
        if "".join(tokens) != conteudo or len(tokens) != 8:
            raise ValueError("Linha Fritz inválida ou glifo desconhecido")
        return ["" if t in "+-" else t[-1].replace("L", "B").replace("l", "b") for t in tokens]
    raise ValueError("Fonte não suportada")


def referencias_pagina(pagina: fitz.Page) -> list[dict]:
    spans = [s for b in pagina.get_text("rawdict")["blocks"] if b["type"] == 0
             for linha in b["lines"] for s in linha["spans"]
             if s["font"] in ("ChessMerida", "DiagramTTFritz")]
    for span in spans:
        span["text"] = "".join(c["c"] for c in span["chars"])
    referencias = []
    for topo in spans:
        fonte, tamanho = topo["font"], topo["size"]
        texto = topo["text"].rstrip()
        if fonte == "ChessMerida":
            texto = "".join(chr(ord(c) - 0xF000) if 0xF000 <= ord(c) < 0xF100 else c for c in texto)
            if texto != "1222222223":
                continue
        elif texto != "XABCDEFGHY":
            continue
        linhas = sorted([s for s in spans if s["font"] == fonte
            and abs(s["bbox"][0] - topo["bbox"][0]) < tamanho * .1
            and abs(s["size"] - tamanho) < .1
            and topo["bbox"][1] + tamanho * .5 < s["bbox"][1] < topo["bbox"][1] + tamanho * 9.5],
            key=lambda s: s["bbox"][1])
        if len(linhas) != 9:
            continue
        rodape = linhas[-1]["text"].rstrip()
        if fonte == "ChessMerida":
            rodape = "".join(chr(ord(c) - 0xF000) if 0xF000 <= ord(c) < 0xF100 else c for c in rodape)
            if rodape != "7888888889":
                continue
        elif rodape != "xabcdefghy":
            continue
        try:
            tabuleiro = [decodificar_linha(s["text"].rstrip() if fonte == "DiagramTTFritz"
                                         else s["text"], fonte, 8 - i) for i, s in enumerate(linhas[:8])]
        except ValueError:
            continue
        # Fritz usa molduras com largura 0,65 célula e prefixos sem avanço.
        # As posições reais dos glifos evitam deslocar peças ou incluir os ranks.
        passo_y = (linhas[-1]["bbox"][1] - linhas[0]["bbox"][1]) / 8
        x = linhas[0]["chars"][0]["bbox"][2]
        glifo_direito = "\uf035" if fonte == "ChessMerida" and linhas[0]["text"][0] == "\uf034" else (
            "5" if fonte == "ChessMerida" else "(")
        bordas = [c for c in linhas[0]["chars"] if c["c"] == glifo_direito]
        if len(bordas) != 1:
            continue
        direita = bordas[0]["bbox"][0]
        y = linhas[0]["bbox"][1]
        quadro = np.array([[x, y], [direita, y],
                           [direita, y + passo_y * 8], [x, y + passo_y * 8]], np.float32)
        quadro = np.array([tuple(fitz.Point(*p) * pagina.rotation_matrix) for p in quadro], np.float32)
        referencias.append({"fonte": fonte, "posicao": compactar_tabuleiro(tabuleiro), "quadro": quadro.tolist()})
    return referencias


def gerar_referencias(pdf: Path, relatorio: dict) -> tuple[dict, dict]:
    anotacoes = {"sha256_pdf": relatorio["sha256_pdf"], "origem": "Texto PDF: ChessMerida/DiagramTTFritz",
                "sha256_recortes": relatorio.get("sha256_recortes"),
                "diagramas": {}}
    correspondencia = {"referencias": [], "nao_detectadas": [], "detectadas": 0}
    candidatos_por_pagina = {}
    for candidato in relatorio["candidatos"]:
        candidatos_por_pagina.setdefault(candidato["pagina"], []).append(candidato)
    with fitz.open(pdf) as documento:
        for numero in range(1, len(relatorio["paginas"]) + 1):
            usados = set()
            for referencia in referencias_pagina(documento[numero - 1]):
                ref = np.array(referencia["quadro"], np.float32)
                opcoes = []
                for candidato in candidatos_por_pagina.get(numero, []):
                    if candidato["id"] in usados:
                        continue
                    q = np.array(candidato["quadro_pontos_pdf"], np.float32)
                    area_a, area_b = cv2.contourArea(ref), cv2.contourArea(q)
                    inter = cv2.intersectConvexConvex(ref, q)[0]
                    iou = inter / (area_a + area_b - inter) if area_a + area_b > inter else 0
                    opcoes.append((iou, candidato["id"]))
                iou, identificador = max(opcoes, default=(0, None))
                referencia.update(pagina=numero, candidato=identificador if iou >= .45 else None, iou=iou)
                correspondencia["referencias"].append(referencia)
                if iou < .45:
                    correspondencia["nao_detectadas"].append(referencia)
                    continue
                usados.add(identificador)
                correspondencia["detectadas"] += 1
                anotacoes["diagramas"][identificador] = {"posicao": referencia["posicao"], "fonte": referencia["fonte"]}
    return anotacoes, correspondencia
