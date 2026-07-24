"""Converte o PNG principal para o formato multi-resolucao do Windows."""

from pathlib import Path

from PIL import Image


RAIZ = Path(__file__).resolve().parents[1]
ORIGEM = RAIZ / "icon" / "icon.png"
DESTINO = RAIZ / "icon" / "icon.ico"


def main() -> None:
    if not ORIGEM.is_file():
        raise SystemExit(f"Icone nao encontrado: {ORIGEM}")
    with Image.open(ORIGEM) as imagem:
        imagem.convert("RGBA").save(
            DESTINO,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    print(f"Icone Windows preparado em: {DESTINO}")


if __name__ == "__main__":
    main()
