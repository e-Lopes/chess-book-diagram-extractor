"""Padroniza um livro a partir de posições revisadas e cantos em pontos PDF.

Exemplo de JSON: {"diagramas": [{"pagina": 1, "quadro_pdf":
[[50, 100], [250, 100], [250, 300], [50, 300]], "posicao": "..."}]}
Os cantos acompanham a página renderizada: superior esquerdo, superior
direito, inferior direito, inferior esquerdo. A página começa em 1.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tabuleiros_padronizados import DiagramaPadronizado, exportar_pdf_padronizado


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origem", type=Path)
    parser.add_argument("destino", type=Path)
    parser.add_argument("--diagramas", type=Path, required=True)
    parser.add_argument("--idioma", choices=("pt", "en"), default="pt")
    args = parser.parse_args()
    dados = json.loads(args.diagramas.read_text(encoding="utf-8"))
    diagramas = [DiagramaPadronizado(int(item["pagina"]),
        tuple(tuple(float(v) for v in ponto) for ponto in item["quadro_pdf"]), item["posicao"])
        for item in dados["diagramas"]]
    resultado = exportar_pdf_padronizado(args.origem, args.destino, diagramas, idioma=args.idioma,
        progresso=lambda a, t: print(f"{a}/{t} diagramas", flush=True) if a % 50 == 0 or a == t else None)
    print(resultado)


if __name__ == "__main__":
    main()
