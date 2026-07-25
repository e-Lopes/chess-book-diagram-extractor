# Algoritmos

## Detecção dos tabuleiros

### 1. Renderização

O PyMuPDF transforma cada página em uma imagem RGB a 240 DPI. Esse valor busca
preservar as linhas e peças de livros digitalizados sem elevar excessivamente
tempo e memória.

### 2. Geração de candidatos

O OpenCV converte a página para tons de cinza e produz variações binárias e
morfológicas para encontrar contornos. Quadriláteros aproximadamente quadrados,
dentro dos limites proporcionais à página, tornam-se candidatos. A perspectiva
é corrigida antes da avaliação; assim, pequenas inclinações de digitalização não
impedem a divisão regular do tabuleiro.

### 3. Verificação da estrutura 8×8

Cada recorte é normalizado e analisado em 64 regiões. A pontuação combina:

- correlação com um padrão alternado de casas;
- contraste entre as duas paridades;
- consistência da alternância horizontal e vertical;
- existência e continuidade da moldura externa;
- cobertura de tinta recorrente nas casas escuras.

A alternância bidimensional é obrigatória. Molduras, fotografias de peças e
tabelas de texto não podem ser aceitas apenas por serem quadradas. A cobertura
das casas escuras foi adicionada especialmente para rejeitar tabelas 8×8 de
símbolos, que podem imitar a periodicidade mas não o fundo de um tabuleiro.

O modo normal aceita candidatos com pontuação mínima `0,20`. Os requisitos
internos de correlação, contraste e consistência também impedem que uma soma de
características fracas compense a ausência da grade.

### 4. Duplicatas e ordem

Contornos internos e externos podem representar o mesmo tabuleiro. Os
candidatos são ordenados por confiança e sobreposições são eliminadas usando
IoU `0,55` ou cobertura de `78%` da menor área. O resultado final é ordenado por
número da página e posição visual, de cima para baixo e da esquerda para a
direita.

### 5. Recuperação em livros alternados

Alguns livros de problemas repetem o padrão “página com dois diagramas, página
com texto”. Quando há pelo menos quatro páginas com dois tabuleiros e 80% delas
compartilham a mesma paridade de página, páginas esperadas com zero ou apenas um
candidato passam novamente pelo detector.

Essa segunda passagem usa limiar `0,15` e requisitos estruturais mais sensíveis,
mas somente nas páginas compatíveis com o padrão. O objetivo é recuperar um
diagrama fraco sem relaxar todo o livro e multiplicar falsos positivos.

## Reconhecimento Forsyth

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
variações de borda, são avaliados recuos proporcionais de `0`, `1%`, `2%`, `3%`
e `4,5%`; fica a divisão com melhor confiança média.

O modelo retorna probabilidades para casa vazia e doze peças. Internamente o
projeto usa o alfabeto inglês `K/Q/R/B/N/P` e minúsculas para as pretas. Somente
na entrada e saída há conversão para o português `R/D/T/B/C/P`. Manter um único
alfabeto interno evita duplicar regras e dados de aprendizado.

Apenas o campo de posicionamento é produzido. Turno, roque, en passant e
contadores não podem ser inferidos de uma imagem estática e, portanto, não são
inventados.

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
- o diagrama não foi sinalizado como possível falso positivo.

O conjunto mantém exemplos representativos e evita dezenas de cópias quase
idênticas. Edições manuais válidas viram referências fortes para a impressão
digital daquele PDF.

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

## Geração dos documentos

O primeiro resultado é um PDF A4 branco com um tabuleiro centralizado por
página, além da página original e confiança de detecção. Quando o fluxo Forsyth
é concluído, o PDF anotado:

- usa uma imagem por página;
- mostra a posição e a página original em texto maior e em negrito;
- omite a confiança, que é um dado de diagnóstico;
- exclui recortes marcados como não tabuleiro;
- acrescenta ao final um índice com uma posição por linha, na mesma ordem dos
  diagramas e sem o prefixo “Forsyth”.

## Limitações conhecidas

- Digitalizações muito degradadas, bordas ausentes ou diagramas parcialmente
  cortados podem não fornecer estrutura suficiente.
- Uma tabela ou ilustração extremamente semelhante a um tabuleiro ainda pode
  ser aceita; o visualizador oferece a exclusão explícita.
- O modelo pode confundir peças com silhuetas próximas. A comparação pelo livro
  reduz o problema, mas não substitui treinamento com o estilo específico.
- As taxas são heurísticas e úteis para ordenar decisões internas; não são uma
  probabilidade estatística calibrada de que toda a posição esteja correta.

