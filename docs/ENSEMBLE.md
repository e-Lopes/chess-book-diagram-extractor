# Ensemble de reconhecimento de peças

O reconhecedor padrão usa três redes treinadas e calcula uma distribuição
combinada para cada uma das 64 casas. O processamento continua local e não
baixa pesos durante o uso do aplicativo.

| Modelo | Fonte dos pesos | Peso inicial | Pré-processamento |
| --- | --- | ---: | --- |
| fenshot | [scoriiu/fenshot](https://github.com/scoriiu/fenshot), commit `3f358e6e075cb08bf8f70d4349080ec0ee889a13` | 0,60 | Cinza OpenCV, resize linear |
| Linrock | [linrock/chessboard-recognizer](https://github.com/linrock/chessboard-recognizer), release `v0.5`, `nn.zip` | 0,30 | Resize RGB Pillow bilinear, depois cinza |
| Chessbot | [Elucidation/tensorflow_chessbot](https://github.com/Elucidation/tensorflow_chessbot/tree/34fe562eaaf9889a155133b2ceed6c007c6c9256), grafo congelado | 0,10 | Cinza Pillow, resize bilinear |

Os dois modelos TensorFlow foram convertidos para ONNX. O conversor compara
probabilidades e classes previstas com a implementação original antes de
substituir o arquivo final. TensorFlow não faz parte das dependências do app.
O catálogo `models/ensemble.json` contém hashes, pesos, temperaturas e o preparo
específico de cada membro. Cópias de um mesmo modelo não são aceitas como membros
adicionais. Todos os arquivos ONNX e suas licenças acompanham o instalador.

## Decisão por casa

Todos os membros avaliam a mesma hipótese de alinhamento do diagrama. Cada um
aplica seu próprio preparo e suas classes são reordenadas para
`1KQRBNPkqrbnp`: vazia e as doze peças. A enumeração interna das casas é
`a1…h8`, preservando a orientação apresentada na imagem.

Para casa `s` e classe `c`, a votação usa:

```text
probabilidade_combinada[s,c] = soma(peso[m] * probabilidade[m,s,c]) / soma(peso)
classe_eleita[s] = argmax(probabilidade_combinada[s,:])
```

Uma temperatura opcional suaviza ou concentra as probabilidades de cada membro
antes da combinação. Todas as temperaturas começam em 1, sem ajuste. Os pesos
60/30/10 são uma configuração inicial conservadora, não o resultado de uma
calibração estatística em uma coleção de livros. Os valores combinados também
não são probabilidades calibradas da correção da posição completa.

Cada casa guarda o voto, a confiança e as treze probabilidades de todos os
modelos, além da proporção ponderada dos votos que apoiam a classe eleita.
Um modelo individual muito confiante não decide sozinho quando a distribuição
combinada favorece outra classe.

## Divergências

Uma casa fica pendente de conferência quando menos de 75% do peso dos votos
apoia a classe eleita ou quando outro membro aponta uma alternativa com pelo
menos 70% de confiança. O diagrama continua recebendo uma notação, mas não é
marcado como confiável. O visualizador mostra um aviso curto com as coordenadas
a conferir. Edições manuais mantêm prioridade.

Casas com divergência não alimentam automaticamente as referências de peças
ou os fundos usados na comparação pelo livro. Isso evita transformar uma
disputa entre modelos em um exemplo de aprendizado confiável.

Na v0.4.1, pequenas bolinhas indicativas podem determinar vazio por geometria.
Essas casas mantêm os votos originais para diagnóstico, são marcadas com
`marcador_vazio` e ficam fora das referências automáticas e dos alertas de
divergência. Essa regra é distinta da votação dos modelos e está descrita em
[Algoritmos](ALGORITMOS.md#bolinhas-indicativas).

## Avaliação reproduzível

```powershell
python tools/avaliar_ensemble.py
```

O comando salva `build/avaliacao-ensemble.json`, com posições, erros por casa,
matriz de confusão, casas ocupadas, tempos e erros classificados como confiáveis.
Modelos individuais e o ensemble usam o mesmo detector e a mesma busca pelos
seis recuos do tabuleiro. A orientação é a da imagem, inclusive nas duas
amostras mostradas pela perspectiva das pretas.

Resultado nas cinco fixtures disponíveis:

| Reconhecedor | Posições exatas | Casas corretas | Posições erradas marcadas confiáveis |
| --- | ---: | ---: | ---: |
| fenshot | 5/5 | 320/320 | 0 |
| Linrock | 3/5 | 279/320 | 0 |
| Chessbot | 2/5 | 271/320 | 1 |
| Ensemble | 5/5 | 320/320 | 0 |

O ensemble mantém o acerto do modelo principal nessas amostras e deixa três
posições pendentes devido a divergências. Este conjunto não demonstra ganho de
acurácia sobre o fenshot sozinho. Para medir esse ganho, adicionar diagramas de
livros reais com falhas do modelo principal e separar calibração e teste por
livro e estilo. Avaliar também a taxa de posições pendentes, para que reduzir
erros classificados como confiáveis não esconda excesso de pedidos de revisão.

Um manifesto próprio pode ser passado com `--manifest caminho/posicoes.json`.
Cada entrada contém `arquivo`, relativo ao manifesto, e `posicao`, apenas o
posicionamento FEN inglês. Esta ferramenta espera exatamente um tabuleiro por
imagem; avaliação de páginas inteiras com vários diagramas exige correspondência
entre caixas detectadas e caixas anotadas.

A reavaliação do pipeline completo da v0.4.1 coincidiu nas 341 posições de
referência tipográfica do livro fornecido, após remover falsos ocupantes
causados por pontos. Esse resultado inclui heurísticas de geometria, não
apenas o ensemble. Os modelos individuais não foram reavaliados com essas
regras; não se conclui vantagem sobre eles nem sobre outros livros.
Veja [a avaliação e o protocolo](AVALIACAO_LIVRO.md#resultado-da-v041).

## Recriar os pesos convertidos

Para testar um PDF inteiro, incluindo páginas com vários estilos e diagramas,
consulte [a avaliação por livro](AVALIACAO_LIVRO.md). Ela salva recortes, votos
por casa e uma revisão HTML, e mede acurácia somente onde há uma referência.

Em um ambiente de desenvolvimento com TensorFlow e `onnx==1.16.2`:

A conversão incluída foi validada com Python 3.12, TensorFlow 2.19.0 e ONNX
1.16.2. Esses componentes só são necessários para recriar os pesos.

```powershell
python tools/preparar_modelos_ensemble.py
```

O comando baixa fontes fixas, verifica seus hashes e converte os pesos sem
executar código dos repositórios externos. `--offline` reutiliza fontes já
validadas em `build/model_sources`. A conversão exige que a classe prevista
seja idêntica e que as probabilidades fiquem dentro da tolerância numérica.

Para comparar com o reconhecedor anterior pela API Python:

```python
reconhecedor = ReconhecedorForsyth(usar_ensemble=False)
```

Novos classificadores ONNX podem ser adicionados ao catálogo quando obedecerem
ao contrato de entrada `[64,1024]`, saída `[64,13]`, probabilidades normalizadas
e classes completas. Arquiteturas diferentes precisam de conversão ou de um
novo adaptador. Cada inclusão também precisa de licença, hash, avaliação e
atualização dos arquivos empacotados no instalador.
