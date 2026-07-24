"""Gera versao Python e metadados do executavel para um build especifico."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "build" / "generated"


def validar_versao(valor: str) -> tuple[int, int, int, int]:
    correspondencia = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", valor)
    if not correspondencia:
        raise ValueError("Use uma versao como 1.2.3 ou 1.2.3-dev.")
    numeros = tuple(int(item) for item in correspondencia.groups())
    if any(item > 65535 for item in numeros):
        raise ValueError("Cada parte numerica da versao deve ser menor que 65536.")
    return numeros[0], numeros[1], numeros[2], 0


def gerar(versao: str, repositorio: str = "", editor: str = "E-Lopes") -> None:
    arquivo_versao = validar_versao(versao)
    DESTINO.mkdir(parents=True, exist_ok=True)
    (DESTINO / "_build_config.py").write_text(
        f"BUILD_VERSION = {versao!r}\nGITHUB_REPOSITORY = {repositorio!r}\nPUBLISHER = {editor!r}\n",
        encoding="utf-8",
    )
    info = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={arquivo_versao!r}, prodvers={arquivo_versao!r}, mask=0x3f,
    flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable(u'041604B0', [
      StringStruct(u'CompanyName', u'{editor}'),
      StringStruct(u'FileDescription', u'Chess Book Diagram Extractor'),
      StringStruct(u'FileVersion', u'{versao}'),
      StringStruct(u'InternalName', u'ChessBookDiagramExtractor'),
      StringStruct(u'OriginalFilename', u'ChessBookDiagramExtractor.exe'),
      StringStruct(u'ProductName', u'Chess Book Diagram Extractor'),
      StringStruct(u'ProductVersion', u'{versao}')
    ])]),
    VarFileInfo([VarStruct(u'Translation', [1046, 1200])])
  ]
)
"""
    (DESTINO / "version_info.txt").write_text(info, encoding="utf-8")
    print(f"Metadados da versao {versao} preparados em {DESTINO}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", default="")
    parser.add_argument("--publisher", default="E-Lopes")
    argumentos = parser.parse_args()
    try:
        gerar(argumentos.version, argumentos.repository, argumentos.publisher)
    except ValueError as erro:
        parser.error(str(erro))


if __name__ == "__main__":
    main()
