# TODO — Biblioteca, visualizador e exportação PGN

O visualizador existente em `revisor_forsyth.py`, que já exibe os diagramas e
permite editar posições, será usado como base para estas funcionalidades.

## Visualizador de diagramas

- [x] Disponibilizar o visualizador de diagramas na interface principal, abaixo
      do botão **Extrair diagramas**, permitindo reabrir livros já processados.
- [x] Permitir visualizar cada diagrama, navegar entre eles e editar sua FEN
      diretamente no visualizador.
- [x] Adicionar o controle **White to Move / Black to Move** para cada posição e
      incorporar essa informação à FEN completa.

## Conversão e exportação PGN

- [x] Integrar o conversor de FENs para PGN ao projeto.
- [x] Permitir definir e editar o campo `Annotator` associado ao livro e usado
      na exportação PGN.
- [x] Adicionar o botão **Exportar PGN** no visualizador.
- [x] Ao exportar, carregar todas as posições salvas para o livro e solicitar:
  - nome do `Annotator`, inicialmente preenchido com o valor já associado ao
    livro;
  - nome e local do arquivo `.pgn`, por meio de uma janela **Salvar como**.
- [x] Gerar uma entrada PGN por diagrama, incluindo `SetUp`, `FEN`, `Annotator`
      e o lado a jogar.

## Memória e biblioteca interna

- [x] Salvar internamente, por livro, a lista final de FENs, o lado a jogar e os
      metadados necessários para futuras edições.
- [x] Criar uma biblioteca interna de livros processados, contendo uma cópia
      própria do PDF de diagramas e seus dados.
- [x] Manter o visualizador funcionando mesmo que o usuário mova ou exclua a
      cópia externa escolhida durante a extração.
- [x] Tratar o PDF salvo no destino escolhido pelo usuário como uma cópia
      exportada; a biblioteca interna será a fonte permanente do aplicativo.

## Testes

- [x] Testar a persistência e a reabertura dos livros da biblioteca interna.
- [x] Testar a edição das FENs e a alternância do lado a jogar.
- [x] Testar a definição do `Annotator` e a exportação do arquivo PGN.
