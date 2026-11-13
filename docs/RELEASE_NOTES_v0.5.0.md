# v0.5.0 — importar um diagrama a partir de uma imagem

Agora é possível obter a posição de um único diagrama sem processar um livro
inteiro. Copie a imagem de um tabuleiro visto em um site, PDF ou captura de
tela e pressione `Ctrl+V` na janela principal, ou use o novo botão
**Importar diagrama de imagem**.

## Mudanças

- Importação de diagramas avulsos por **Colar imagem** (`Ctrl+V`) ou
  **Abrir arquivo…**, com PNG, JPG, GIF, BMP, WEBP e TIFF. Arquivos de imagem
  copiados no Explorer também são aceitos.
- O tabuleiro é localizado mesmo no meio de uma página ou de uma captura maior,
  inclusive em fotos levemente inclinadas, e reconhecido pelos mesmos três
  modelos usados nos livros.
- Original e reconstrução lado a lado, com edição por clique ou arraste das
  peças, como no visualizador da biblioteca.
- **Copiar FEN** copia a FEN completa em notação inglesa, aceita por Lichess,
  ChessBase e outros programas; **Abrir no Lichess** abre a posição no editor.
- **Inverter tabuleiro** para diagramas com as pretas embaixo, com aviso
  automático quando a posição dos peões sugere essa orientação.
- O campo **Posição** aceita FEN completa e letras inglesas ou portuguesas,
  convertendo para a notação escolhida e definindo o lado a jogar.

As posições importadas dessa forma não são salvas na biblioteca.

## Validação

186 testes locais passaram. As cinco capturas públicas de sites usadas como
referência (Lichess, Reddit e tabuleiro azul) foram reconhecidas exatamente
na resolução original, pela metade, em JPEG de qualidade 70 e em GIF.
Também são verificados diagramas de livro colados como recorte justo ou no
meio de uma página de texto, fotos inclinadas, PNG de 16 bits, transparência
e imagens copiadas com alfa zerado pela área de transferência do Windows.

## Instalação e atualização

Use `ChessBookDiagramExtractor-Setup-v0.5.0.exe` ou o alias
`ChessBookDiagramExtractor-Setup.exe` nos assets desta release. O instalador
para Windows 10/11 de 64 bits atualiza a instalação existente, e quem já usa a
v0.4.1 recebe a oferta pelo atualizador do aplicativo. Os livros salvos
anteriormente continuam compatíveis.
`SHA256SUMS.txt` e `release.json` registram hashes e tamanhos dos instaladores.

## Code signing policy

Free code signing provided by [SignPath.io](https://signpath.io/), certificate
by [SignPath Foundation](https://signpath.org/).

Releases published before completion of the SignPath integration may be unsigned.

- [Code signing policy](https://github.com/e-Lopes/chess-book-diagram-extractor/blob/main/CODE_SIGNING_POLICY.md)
- [Privacy policy](https://github.com/e-Lopes/chess-book-diagram-extractor/blob/main/PRIVACY.md)
