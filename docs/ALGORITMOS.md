# Algoritmos

## Detecção dos tabuleiros

### 1. Renderização

O PyMuPDF transforma cada página em uma imagem RGB a 240 DPI. Esse valor busca
preservar as linhas e peças de livros digitalizados sem elevar excessivamente
tempo e memória.

### 2. Geração de candidatos

O OpenCV converte a página para tons de cinza e produz variações binárias e
morfológicas para encontrar contornos. Esses contornos são combinados com as
caixas de imagens raster informadas pelo próprio PDF. Regiões aproximadamente
quadradas e de tamanho relevante tornam-se candidatas. A perspectiva é
corrigida antes da avaliação; assim, pequenas inclinações não impedem o recorte.

Uma máscara adicional preserva linhas longas horizontais e verticais. Ela
separa a moldura de hachuras e coordenadas externas que poderiam inclinar o
retângulo ajustado mesmo quando o tabuleiro está reto.

As retas dos quatro lados são ajustadas aos pixels do contorno com uma perda
robusta. Isso evita que cantos arredondados ou a simplificação do contorno
desloquem as casas durante a correção de perspectiva. O ajuste só é aplicado
quando há evidência suficiente em cada lado e a alteração dos cantos é pequena.
Diagramas entre 4,5% e aproximadamente 100% da menor dimensão da página são
considerados, com um mínimo de 64 pixels por lado.

Para imagens raster no PDF, os cantos são obtidos da matriz de transformação
da imagem e transformados para a orientação renderizada da página. Isso respeita
rotação e recorte da página, conforme as convenções de coordenadas do
[PyMuPDF](https://pymupdf.readthedocs.io/en/latest/page.html#Page.rotation_matrix).

### 3. Verificação da estrutura 8×8

Cada recorte é normalizado e analisado em 64 regiões. A pontuação combina:

- correlação com um padrão alternado de casas;
- contraste entre as duas paridades;
- consistência da alternância horizontal e vertical;
- existência e continuidade da moldura externa;
- cobertura de tinta recorrente nas casas escuras.

O fundo é estimado tanto na região central quanto nos quatro cantos de cada
casa. Entre os cantos, a região menos escurecida reduz a interferência das
bases e coroas de peças grandes; a hachura permanece visível no fundo.

A forma quadrada apenas gera uma região candidata: ela só entra no resultado
se sua pontuação alcançar o limiar (0,20 por padrão), incluindo as regiões
vindas de imagens embutidas no PDF. Fotos, mapas, texto e letras grandes não
podem compensar a ausência da alternância bidimensional 8×8.

A opção explícita `aceitar_quadrados=True` permanece disponível por código
para diagnóstico, mas não é usada no fluxo normal. No livro de 601 páginas,
o filtro reduziu 799 recortes para 594, removendo 205 regiões sem grade e
preservando os 341 diagramas com referência independente. Isso não certifica
os 253 diagramas restantes, que continuam sujeitos à revisão.

Para livros salvos antes desse filtro, a biblioteca avalia os recortes ao
carregar e oculta os descartados na navegação e nas exportações PGN e de
padronização. O campo opcional `excluir` distingue metadados antigos (ausente)
de uma escolha já salva. Uma restauração manual (`excluir=False`) é preservada
na próxima abertura, mesmo quando a pontuação estrutural é baixa.

### 4. Duplicatas e ordem

Contornos internos e externos podem representar o mesmo tabuleiro. Os
candidatos são ordenados por confiança. A comparação usa a interseção dos
quadriláteros, na mesma página, com IoU `0,55` ou cobertura de `78%` da menor
área quando os tamanhos são comparáveis. Um contorno parcial sem evidência de
grade, com pelo menos 90% da área dentro de um tabuleiro confirmado, também é
removido. Molduras muito maiores não eliminam os diagramas individuais.

O resultado segue página e linha visual. Pequenos desalinhamentos verticais
de até 15% da altura do menor diagrama na comparação não invertem a ordem da
esquerda para a direita. Linhas distintas continuam de cima para baixo.

## Reconhecimento Forsyth

### Alinhamento e restrição dos reis

`alinhamento_tabuleiro.py` mede as transições de cor entre casas, procurando
sete limites internos regularmente espaçados por eixo. As margens esquerda,
direita, superior e inferior são independentes. Uma faixa externa só é removida
quando tem tamanho significativo e evidencia seis ou mais transições fortes,
com ganho sobre a divisão sem recorte. Molduras pequenas simétricas permanecem
na busca de recuos do reconhecedor, evitando somar dois recortes.
O recorte original e suas coordenadas no PDF são preservados.

`restricoes_reconhecimento.eleger_com_reis` escolhe duas casas distintas,
uma para cada rei, maximizando a probabilidade conjunta das 64 casas. Compara
a probabilidade do rei com a melhor classe alternativa que não seja rei.
As demais casas usam sua melhor alternativa não rei. Uma posição inicialmente
com exatamente um rei de cada cor permanece igual. Votos e probabilidades
originais são mantidos; a confiança da nova classe é lida da matriz original,
sem ser elevada artificialmente. Mudanças são registradas em `ajustes_reis`
e impedem que o resultado seja declarado confiável sem revisão.

Nos casos fornecidos, o círculo em f7 (página 262) virou vazio, preservando o
rei branco de h1; a moldura assimétrica do tabuleiro laranja (página 565) foi
removida para reconhecimento. Os dois casos têm testes de regressão.
Na validação da v0.4.1, após o tratamento das bolinhas, as 341 referências
tipográficas tiveram posições exatas e 21.824/21.824 casas corretas. Os números
anteriores eram 333 posições e 21.784 casas corretas. Esses resultados não
certificam as posições sem referência anotada; veja [avaliação do livro](AVALIACAO_LIVRO.md).

### Bolinhas indicativas

`marcadores_diagrama.casas_com_bolinhas` avalia as casas da imagem alinhada,
normalizadas para 64×64. Uma abertura morfológica remove hachuras finas. O
marcador precisa ser um único componente pequeno, aproximadamente circular,
próximo ao centro e sem traços horizontais ou verticais significativos que
indiquem corpo ou base de uma peça. Peões e contornos de peças brancas são
verificados por esses limites; não basta encontrar uma região preta arredondada.

As casas identificadas são vazias na matriz usada para a eleição, preservando
as probabilidades e os votos originais. Elas não podem receber um rei e não
alimentam referências automáticas de peças. A revisão pelo livro também não
as transforma em peças. A confiança geral e os alertas de divergência são
calculados sobre as demais casas. Se não houver duas casas candidatas para os
reis, a posição permanece inválida para conferência, sem inventar reis nos pontos.

O recorte `p0309-d05` verifica os sete marcadores e preserva todas as peças.
A heurística é voltada a pequenos pontos pretos; setas, círculos grandes,
marcadores coloridos ou pontos sobre peças precisam de avaliação própria.

### Convenção de orientação

O recorte é usado na orientação apresentada pelo livro. A casa superior
esquerda é `a8`, considerada clara, e a leitura segue da esquerda para a direita
e de cima para baixo. Não há rotação automática porque os livros atendidos usam
diagramas padronizados e uma rotação inferida incorretamente seria difícil de
perceber.

### Modelo

O reconhecedor usa localmente o modelo `chess-tiles-v2.onnx`, originado do
projeto fenshot no commit
`3f358e6e075cb08bf8f70d4349080ec0ee889a13`. Antes de carregar, o código valida
o SHA-256 esperado:

`883F6A8E639E6D6B6399B3FDA0508AD772E3C6F9CEFA2E678A13F27B9FA6248D`

O tabuleiro é dividido em 64 imagens de 32×32 pixels. Para compensar pequenas
variações de borda, são avaliados recuos proporcionais de `0`, `0,5%`, `1%`,
`2%`, `3%` e `4,5%`. A seleção combina a confiança média (50%), a confiança
média das casas ocupadas (25%) e a média das oito casas menos seguras (25%),
com uma penalidade por inconsistências básicas de quantidade de peças e reis.
Assim, muitas casas vazias confiáveis não escondem uma peça mal recortada.

A saída precisa ter formato `64×13`, valores finitos entre zero e um e soma
unitária por casa. Fora das restrições dos reis e dos marcadores, a leitura
inicial preserva a classe mais provável; não
troca peão por cavalo, ou o inverso, somente por causa da fileira ou de um
empate. Eventuais trocas exigem a evidência visual descrita na revisão pelo
livro. Casas com confiança abaixo de 70% ou margem abaixo de 20 pontos são
identificadas pelas coordenadas no aviso de revisão.

O modelo retorna probabilidades para casa vazia e doze peças. Internamente o
projeto usa o alfabeto inglês `K/Q/R/B/N/P` e minúsculas para as pretas. Somente
na entrada e saída há conversão para o português `R/D/T/B/C/P`. Manter um único
alfabeto interno evita duplicar regras e dados de aprendizado.

Apenas o campo de posicionamento é produzido. Turno, roque, en passant e
contadores não podem ser inferidos de uma imagem estática e, portanto, não são
inventados.

## Ensemble

Antes da revisão pelo livro, a leitura padrão combina três redes ONNX:
fenshot, Linrock e TensorFlow Chessbot. Cada uma respeita seu pré-processamento,
e suas probabilidades são alinhadas nas mesmas treze classes. A votação usa
pesos iniciais de 60%, 30% e 10%, com eleição independente por casa. Casas com
divergência forte permanecem pendentes e não geram referências automáticas.
Consulte [Ensemble](ENSEMBLE.md) para fontes, contratos e avaliação comparativa.

## Revisão automática baseada no livro

Impressões antigas apresentam estilos consistentes dentro do mesmo livro, mas
muito diferentes entre livros. A segunda passagem usa essa repetição como uma
fonte local de evidência.

### Fundo e descritor

Para cada paridade, o sistema calcula a mediana das casas vazias muito
confiáveis. O fundo claro ou hachurado é subtraído antes da comparação. A imagem
residual é descrita por HOG, que representa a silhueta, combinado com uma versão
reduzida em pixels. A similaridade entre descritores é medida por cosseno.

Referências sempre são separadas por classe e paridade. Uma dama em casa clara
nunca serve para corrigir diretamente uma casa escura. Essa regra é importante
porque o hachurado altera bastante a aparência da mesma peça.

### Formação das referências

Uma previsão automática só vira referência quando:

- a confiança é no mínimo 85%;
- a margem sobre a segunda classe é no mínimo 30 pontos percentuais;
- existem pelo menos três exemplos em dois diagramas diferentes;
- o diagrama não foi sinalizado como possível falso positivo;
- a casa não tem divergência entre modelos nem marcador de vazio.

O conjunto mantém exemplos representativos e evita dezenas de cópias quase
idênticas. Edições manuais válidas viram referências fortes para a impressão
digital daquele PDF.

Uma nova edição da mesma imagem substitui seu rótulo manual anterior para
evitar referências contraditórias. Excluir um diagrama também retira sua
contribuição aos fundos e às referências na próxima revisão.

### Quando uma casa é revista

A revisão considera casas com confiança abaixo de 70%, margem abaixo de 20
pontos ou pertencentes aos pares de confusão conhecidos:

- peão branco × cavalo branco (`P/N`);
- peão preto × cavalo preto (`p/n`);
- peão preto × bispo preto (`p/b`);
- bispo branco × dama branca (`B/Q`).

Uma classe alternativa precisa estar entre as três hipóteses originais. Os três
vizinhos visuais mais próximos devem concordar, a similaridade precisa ser
compatível com a distribuição da classe e o escore combinado deve superar o
original em pelo menos `0,10`. O escore usa 45% da probabilidade ONNX e 55% da
similaridade com as referências.

Por fim, a troca não pode piorar regras básicas de plausibilidade: um rei por
cor, no máximo oito peões, dezesseis peças por cor e trinta e duas no total.
Essas regras são proteções, não motivos isolados para criar uma peça.

Se qualquer requisito falhar, a classificação original é mantida. A prioridade
é não estragar casas corretas em troca de uma quantidade maior de correções.
Uma posição alterada pela revisão automática permanece pendente de conferência.

## Geração dos documentos

O primeiro resultado é um PDF A4 branco com um tabuleiro centralizado por
página, além da página original e confiança de detecção. Quando o fluxo Forsyth
é concluído, o PDF anotado:

- usa uma imagem por página;
- mostra `posição w/b` e a página original abaixo do diagrama;
- omite a confiança, que é um dado de diagnóstico;
- exclui recortes marcados como não tabuleiro;
- acrescenta ao final um índice com `posição w/b` e, abaixo, o lado a jogar, na
  mesma ordem dos diagramas e sem o prefixo “Forsyth”.

## Limitações conhecidas

- Digitalizações muito degradadas, bordas ausentes ou diagramas parcialmente
  cortados podem não fornecer estrutura suficiente.
- Uma tabela ou ilustração extremamente semelhante a um tabuleiro ainda pode
  ser aceita; o visualizador oferece a exclusão explícita.
- O modelo pode confundir peças com silhuetas próximas. A comparação pelo livro
  reduz o problema, mas não substitui treinamento com o estilo específico.
- As taxas são heurísticas e úteis para ordenar decisões internas; não são uma
  probabilidade estatística calibrada de que toda a posição esteja correta.
