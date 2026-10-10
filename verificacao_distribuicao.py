"""Diagnóstico do aplicativo empacotado, executado sem abrir janelas."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import cv2

from notacao_forsyth import ReconhecedorForsyth, caminho_recurso, validar_posicao
from tabuleiros_padronizados import renderizar_tabuleiro
from version import GITHUB_REPOSITORY, __version__


def verificar() -> dict:
    pasta = caminho_recurso("assets", "pieces", "cburnett")
    manifesto = json.loads((pasta / "manifest.json").read_text(encoding="utf8"))
    for nome, dados in manifesto["arquivos"].items():
        if hashlib.sha256((pasta / nome).read_bytes()).hexdigest() != dados["sha256"]:
            raise RuntimeError(f"Peça com hash incorreto: {nome}")
    if len(manifesto["arquivos"]) != 12:
        raise RuntimeError("As doze peças precisam estar incluídas.")
    for nome in ("cburnett-BSD-3-Clause.txt", "fenshot-LICENSE.txt", "linrock-LICENSE.txt", "legacy-LICENSE.txt"):
        if not caminho_recurso("licenses", nome).is_file():
            raise RuntimeError(f"Licença ausente: {nome}")
    imagem = cv2.imread(str(caminho_recurso("assets", "selftest-board.png")))
    if imagem is None:
        raise RuntimeError("Imagem de diagnóstico ausente.")
    reconhecedor = ReconhecedorForsyth(idioma="en")
    resultado = reconhecedor.reconhecer(imagem)
    esperada = "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R"
    if resultado.posicao != esperada or not validar_posicao(resultado.posicao, "en")[0]:
        raise RuntimeError(f"Reconhecimento de diagnóstico falhou: {resultado.posicao}")
    if renderizar_tabuleiro(esperada, "en", tamanho=256).shape != (256, 256, 3):
        raise RuntimeError("Renderização SVG indisponível.")
    return {"ok": True, "versao": __version__, "repositorio": GITHUB_REPOSITORY,
            "empacotado": bool(getattr(sys, "frozen", False)), "pecas": 12,
            "modelos": [c.nome for c in reconhecedor._configuracoes], "casas": len(resultado.casas),
            "posicao": resultado.posicao}


def executar_cli(argumentos: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    opcoes = parser.parse_args(argumentos)
    try:
        resultado = verificar()
        codigo = 0
    except Exception as erro:
        resultado = {"ok": False, "erro": str(erro), "versao": __version__}
        codigo = 1
    opcoes.report.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf8")
    return codigo
