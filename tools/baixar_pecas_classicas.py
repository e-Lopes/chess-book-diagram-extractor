"""Importa os SVGs Cburnett de Wikimedia Commons sob a opção BSD de 3 cláusulas.

Executado só na manutenção dos assets; o aplicativo usa os arquivos locais.
"""
import hashlib
import json
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "assets" / "pieces" / "cburnett"


def baixar(url):
    pedido = urllib.request.Request(url, headers={"User-Agent":
        "ChessBookDiagramExtractor/0.3 (https://github.com/e-Lopes/chess-book-diagram-extractor)"})
    with urllib.request.urlopen(pedido, timeout=30) as resposta:
        return resposta.read()


def main():
    PASTA.mkdir(parents=True, exist_ok=True)
    manifesto = {"autor": "Colin M. L. Burnett (Cburnett)", "licenca": "BSD-3-Clause",
        "creditos": "Colin M. L. Burnett e colaboradores de Wikimedia Commons; SVGs preservados sem alterações.",
        "arquivos": {}}
    for cor, sufixo in (("w", "lt"), ("b", "dt")):
        for peca in "KQRBNP":
            nome = f"Chess_{peca.lower()}{sufixo}45.svg"
            pagina = f"https://commons.wikimedia.org/wiki/File:{nome}"
            html = baixar(pagina).decode("utf8")
            if "3-clause BSD" not in html:
                raise ValueError(f"A opção de licença BSD precisa ser confirmada: {pagina}")
            digest_nome = hashlib.md5(nome.encode()).hexdigest()
            url = f"https://upload.wikimedia.org/wikipedia/commons/{digest_nome[0]}/{digest_nome[:2]}/{nome}"
            dados = baixar(url)
            raiz = ET.fromstring(dados)
            if not raiz.tag.endswith("svg"):
                raise ValueError(f"Arquivo SVG inválido: {nome}")
            destino = f"{cor}{peca}.svg"
            (PASTA / destino).write_bytes(dados)
            manifesto["arquivos"][destino] = {"fonte": url, "licenca_fonte": pagina,
                "sha256": hashlib.sha256(dados).hexdigest()}
            print(destino, flush=True)
    (PASTA / "manifest.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf8")


if __name__ == "__main__":
    main()
