# Avisos de terceiros

## Peças clássicas Cburnett

Os 12 SVGs em `assets/pieces/cburnett` são obras de Colin M. L. Burnett
(Cburnett) e colaboradores de Wikimedia Commons. São usados sob a opção
BSD de 3 cláusulas disponibilizada nas páginas originais, mantendo os
arquivos sem alterações. Consulte `licenses/cburnett-BSD-3-Clause.txt`.
O aplicativo escala e posiciona os SVGs para formar o tabuleiro.

As fontes de cada arquivo, páginas de licença e hashes estão em
`assets/pieces/cburnett/manifest.json`. Por exemplo:
[rei branco](https://commons.wikimedia.org/wiki/File:Chess_klt45.svg),
[cavalo branco](https://commons.wikimedia.org/wiki/File:Chess_nlt45.svg).

## fenshot

O reconhecimento opcional de posições usa o modelo `chess-tiles-v2.onnx` do
projeto [fenshot](https://github.com/scoriiu/fenshot), fixado no commit
`3f358e6e075cb08bf8f70d4349080ec0ee889a13`.

- SHA-256: `883F6A8E639E6D6B6399B3FDA0508AD772E3C6F9CEFA2E678A13F27B9FA6248D`
- Copyright (c) 2026 SORTINO LABS S.R.L. (coachess.app)
- Licença: MIT — consulte `licenses/fenshot-LICENSE.txt`.

O Chess Book Diagram Extractor valida o SHA-256 antes de carregar o modelo.
O recorte `assets/selftest-board.png` também vem das fixtures MIT desse projeto
e é usado no diagnóstico de distribuição. Consulte `assets/SELFTEST.md`.

## Linrock chessboard-recognizer

O ensemble inclui os pesos da release `v0.5` de
[linrock/chessboard-recognizer](https://github.com/linrock/chessboard-recognizer),
convertidos de TensorFlow para `models/linrock-tiles.onnx`.

- Copyright (c) 2019 Linmiao Xu.
- Licença MIT: `licenses/linrock-LICENSE.txt`.
- SHA-256 ONNX: `73c7d8a45b7d41372af761624edbe4f0c1f152b9a87c7403192c1332cfe66631`.
- Fonte: `https://github.com/linrock/chessboard-recognizer/releases/download/v0.5/nn.zip`.
- SHA-256 do ZIP: `26dead535194b61e97c7d9dc9bb2bd643cbf75dcc8e48e2c9057e026b1c1ff96`.

## TensorFlow Chessbot

O ensemble inclui os pesos de
[Elucidation/tensorflow_chessbot](https://github.com/Elucidation/tensorflow_chessbot),
commit `34fe562eaaf9889a155133b2ceed6c007c6c9256`, convertidos de
`saved_models/frozen_graph.pb` para `models/chessbot-tiles.onnx`.

- Copyright (c) 2016 Sameer Ansari.
- Licença MIT: `licenses/legacy-LICENSE.txt`.
- SHA-256 ONNX: `62b5afb3e247d525ded84e50fa8ba67309368a752eb9bc2f8dd15bae90420d1c`.
- SHA-256 do grafo original: `4dd6247d76600d3a686ce67ebea0aef382a8feed94a7f5c968feb5eac4add7cf`.

As conversões são reproduzíveis por `tools/preparar_modelos_ensemble.py` e
verificadas contra a inferência TensorFlow original. Os três modelos são
executados localmente por ONNX Runtime. Consulte `docs/ENSEMBLE.md`.
