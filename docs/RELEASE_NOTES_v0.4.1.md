# v0.4.1 — edição visual, reconhecimento e retomada da revisão

O livro fica salvo na biblioteca assim que o reconhecimento termina, antes
de abrir a revisão. Fechar a revisão preserva o trabalho; para continuar,
reabra o livro pela lista de livros processados, sem extrair ou reconhecer novamente.

## Mudanças

- Edição por clique ou arraste de peças e vazio; borda azul na casa selecionada.
- Prévia com cache e revisão do livro em segundo plano, com indicador animado.
- Biblioteca com contagens **Diagramas**, **OK** e **Ajustar / conferir** e
  botão **Confirmar diagrama conferido** para posições já verificadas.
- Bolinhas pretas indicativas tratadas como vazio; reis eleitos pela confiança
  e alinhamento de molduras com coordenadas antes do reconhecimento.
- Ensemble de três modelos locais e rejeição de fotos, mapas e texto sem grade 8×8.
- Original e reconstrução lado a lado, peças clássicas e Forsyth abaixo das imagens.
- Exportação PGN disponível com pendências, omitindo as posições inválidas.
- Exportação de uma cópia do livro com diagramas padronizados, preservando o texto.
- Atualizador com SHA-256, cancelamento/nova tentativa e reabertura após instalar.

## Validação

165 testes locais passaram, assim como o diagnóstico do executável empacotado.
As 341 posições de referência tipográfica coincidiram, incluindo 21.824 casas;
os demais diagramas do livro não têm acurácia certificada. A montagem da prévia
caiu de 44,45 ms para 0,90 ms na medição local, sem incluir gravação e validação.
**OK** indica validação e confiança ou conferência manual, não garantia de
reconhecimento perfeito. Consulte [a avaliação](AVALIACAO_LIVRO.md).

## Instalação e atualização

Use `ChessBookDiagramExtractor-Setup-v0.4.1.exe` ou o alias
`ChessBookDiagramExtractor-Setup.exe` nos assets desta release. O instalador
para Windows 10/11 de 64 bits atualiza a instalação existente. Os livros
salvos anteriormente continuam compatíveis; reabra-os pela biblioteca.
`SHA256SUMS.txt` e `release.json` registram hashes e tamanhos dos instaladores.

## Code signing policy

Free code signing provided by [SignPath.io](https://signpath.io/), certificate
by [SignPath Foundation](https://signpath.org/).

Releases published before completion of the SignPath integration may be unsigned.

- [Code signing policy](https://github.com/e-Lopes/chess-book-diagram-extractor/blob/main/CODE_SIGNING_POLICY.md)
- [Privacy policy](https://github.com/e-Lopes/chess-book-diagram-extractor/blob/main/PRIVACY.md)
