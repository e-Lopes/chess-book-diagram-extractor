# Testar um livro com estilos diferentes

`tools/avaliar_livro.py` percorre cada página do PDF usando o detector do
aplicativo e reconhece todos os candidatos com os três modelos do ensemble.
As imagens e relatórios ficam em `build/`, sem modificar o livro original.

```powershell
python tools/avaliar_livro.py --pdf books/TERCEIRA_VERSAO_unida.pdf --saida build/teste-livro-final --referencia-fontes
```

Para repetir apenas o reconhecimento, acrescente `--reusar-recortes`. Para uma
execução curta, use `--paginas 20` e uma pasta de saída separada. O DPI padrão
é 240, igual ao aplicativo.

`--cache-reconhecimento pasta/avaliacao-anterior` reaproveita previsões somente
para imagens de recorte idênticas, verificadas por SHA-256, com o mesmo código
de reconhecimento e catálogo de modelos. Mudanças nas caixas ou nos pesos
exigem nova inferência.

## Conferência visual

Abra `build/teste-livro-final/revisao.html`. A revisão inclui todas as
páginas, inclusive aquelas em que o detector não encontrou candidatos. Os
retângulos vermelhos mostram os recortes; a posição eleita aparece ao lado do
diagrama original. Casas vermelhas no tabuleiro previsto indicam divergência
entre os modelos.

Depois de conferir cada página, informe a quantidade real de diagramas.
Marque recortes que não são tabuleiros e preencha o posicionamento correto,
com as oito linhas da FEN em inglês na orientação da imagem. As anotações são
salvas neste navegador. O botão **Exportar anotações** gera `anotacoes.json`.

```powershell
python tools/avaliar_livro.py --saida build/teste-livro-final --anotacoes caminho/anotacoes.json
```

A avaliação manual salva `metricas-anotadas.json`: posições inteiramente
corretas, acerto nas 64 casas, acerto nas casas ocupadas e erros localizados
por coordenada e modelo. Diferença na contagem por página ajuda a localizar
omissões e candidatos excedentes; contagem igual sozinha não comprova que
as caixas correspondem aos diagramas corretos. Posições sem referência não
entram na acurácia. Anotações de outro PDF ou conjunto de recortes são rejeitadas.

## Referência independente disponível neste PDF

O livro `TERCEIRA_VERSAO_unida.pdf` tem 601 páginas. Uma parte dos diagramas
usa fontes `ChessMerida` e `DiagramTTFritz`, cujos glifos contêm o posicionamento
original. O leitor em `tools/referencia_fontes_pdf.py` aceita somente molduras
completas, oito linhas de oito casas e glifos conhecidos. Os mapas de peças,
cores, prefixos de fundo e casas marcadas foram conferidos visualmente em
amostras do próprio PDF. A referência não depende de previsões das redes.

O parâmetro `--referencia-fontes` gera:

- `referencias-fontes.json`: posicionamentos decodificados do texto original;
- `correspondencia-fontes.json`: caixas de referência, correspondências por
  sobreposição e diagramas não localizados;
- `metricas-fontes.json`: comparação por modelo e fonte, incluindo erros por casa;
- `relatorio.json`: metadados do livro, recortes, previsões e alertas;
- `votos/`: probabilidades das treze classes de cada modelo em cada casa.

Os membros individuais são comparados no alinhamento selecionado pelo ensemble.
Não há adaptação automática de peças pelo livro nesta avaliação. Os pesos
60/30/10 são os iniciais; não foram ajustados usando as referências deste teste.

Essa referência cobre 341 diagramas com essas duas fontes. Imagens rasterizadas,
diagramas de outros estilos e páginas sem diagramas precisam da conferência
visual. A quantidade de candidatos, a confiança do detector e a concordância
entre redes não demonstram que todos os diagramas ou todas as peças estejam
corretos. Os arquivos `books/` e `build/` permanecem fora do versionamento.

## Problemas encontrados e correção

A primeira execução revelou que hachuras e coordenadas podiam se unir ao
contorno externo e inclinar um tabuleiro reto. O detector agora também procura
molduras por linhas longas horizontais e verticais. A estimativa de fundo da
grade considera os quatro cantos das casas, reduzindo a interferência de peças
pretas grandes no centro. O teste sintético correspondente verifica a moldura
e o recorte sem incluir coordenadas externas.

Na primeira avaliação, o ensemble acertou 327 das 341 posições de referência.
Seis diagramas falharam por alinhamento; oito continham marcações de casas
vazias que os modelos podem confundir com peças. A revisão visual permite
examinar esses casos, em vez de tratar a confiança de uma rede como confirmação.

## Histórico: alinhamento, antes do tratamento das bolinhas

A execução final a 240 DPI percorreu as 601 páginas e salvou 799 candidatos,
dos quais 594 receberam evidência de grade acima do limiar do detector. Esses
valores não são uma contagem confirmada de diagramas reais. Os 341 diagramas
de referência foram associados a candidatos por IoU de pelo menos 0,45.

| Reconhecedor | Posições exatas | Casas corretas | Peças em casas ocupadas corretas |
| --- | ---: | ---: | ---: |
| Ensemble | 333/341 | 21.784/21.824 | 7.976/7.976 |
| fenshot | 333/341 | 21.792/21.824 | 7.976/7.976 |
| Linrock | 328/341 | 21.773/21.824 | 7.969/7.976 |
| Chessbot | 239/341 | 21.685/21.824 | 7.877/7.976 |

As seis falhas de alinhamento foram corrigidas. Os 40 erros restantes do
ensemble são peças acrescentadas em casas vazias marcadas com pontos:

- página 308: `p0308-d01`, `p0308-d02`, `p0308-d03`;
- página 309: `p0309-d05`;
- página 404: `p0404-d03`, `p0404-d04`;
- página 405: `p0405-d02`, `p0405-d04`.

Nenhuma posição incorreta desse subconjunto foi marcada como confiável pelo
ensemble; 318 das 341 posições ficaram sem alertas de reconhecimento. Isso
não demonstra ganho de acurácia sobre o fenshot: ele teve oito erros a menos
nas casas vazias marcadas. O ganho observado nesta alteração veio do detector
e do alinhamento, passando de 327 para 333 posições exatas.

A avaliação final reutilizou 577 previsões de recortes idênticos à execução
anterior e inferiu novamente os outros 222. Todas as imagens tiveram seu
SHA-256 registrado. A referência cobre 335 diagramas `ChessMerida` e seis
`DiagramTTFritz`; os outros candidatos e possíveis omissões fora dessas
fontes precisam de anotação independente. Essa execução histórica tinha
108 testes automatizados passando.

## Resultado da v0.4.1

O reconhecimento atual foi executado novamente sobre os 341 recortes com
referência tipográfica, sem reutilizar previsões anteriores e sem adaptação
HOG pelo livro. A avaliação compara as 64 casas e a posição completa com a
referência já extraída das fontes do PDF. O tratamento dos pequenos pontos
pretos resolveu os 40 falsos ocupantes nos oito diagramas listados acima.

| Pipeline | Posições exatas | Casas corretas |
| --- | ---: | ---: |
| Ensemble antes das bolinhas | 333/341 | 21.784/21.824 |
| Ensemble + alinhamento, reis e bolinhas na v0.4.1 | 341/341 | 21.824/21.824 |

Não houve diferenças em relação às 341 posições esperadas. O recorte real
`p0309-d05` também verificou explicitamente e7, f6, g6, h6, g5, h4 e f3 como
vazias, mantendo as peças restantes e os votos individuais dos modelos.
Esse caso é um teste dirigido do mesmo livro; o resultado não mede
generalização para outros estilos, nem equivale a revisar os 594 diagramas
aceitos pelo filtro. Modelos individuais não foram reavaliados nesta rodada,
portanto a tabela histórica não demonstra vantagem do ensemble atual sobre eles.

O [registro da validação](avaliacoes/v0.4.1.json) contém as contagens,
os marcadores do exemplo e a medição local de renderização. A montagem da
imagem da prévia caiu de 44,45 ms (SVG completo) para 0,90 ms (casas em cache).
Essa medição usa uma posição inicial inglesa de 800×800, após aquecer os
recursos: 20 repetições do renderer completo e 100 do renderer da prévia.
Não inclui eventos Tk, validação, salvamento ou revisão do livro. O tempo
depende do computador; a suíte da v0.4.1 passou em 165 testes locais.

Para reavaliar com o código atual, use o comando de avaliação apresentado no
início deste guia. Evite comparar relatórios que reutilizem previsões de outra
versão do reconhecedor. O livro de teste continua fora do repositório.
