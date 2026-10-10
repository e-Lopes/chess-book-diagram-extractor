"""Publica um inventário de tamanho e SHA-256 junto dos instaladores locais."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


def preparar(pasta: Path, versao: str):
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", versao):
        raise ValueError("Versão de release inválida.")
    arquivos = {}
    for nome in (f"ChessBookDiagramExtractor-Setup-v{versao}.exe", "ChessBookDiagramExtractor-Setup.exe"):
        caminho = pasta / nome
        with caminho.open("rb") as arquivo:
            if arquivo.read(2) != b"MZ":
                raise ValueError(f"Executável inválido: {nome}")
        arquivos[nome] = {"sha256": hashlib.sha256(caminho.read_bytes()).hexdigest(),
                          "tamanho": caminho.stat().st_size}
    (pasta / "SHA256SUMS.txt").write_text("".join(f"{d['sha256']}  {n}\n" for n, d in arquivos.items()), encoding="utf8")
    (pasta / "release.json").write_text(json.dumps({"versao": versao, "plataforma": "windows-x64",
                                                  "arquivos": arquivos}, indent=2), encoding="utf8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--directory", type=Path, default=Path("release"))
    args = parser.parse_args()
    preparar(args.directory, args.version)
