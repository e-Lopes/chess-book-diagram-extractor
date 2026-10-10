# Testes e qualidade

A versão 0.4.1 passou em 165 testes locais. Os casos verificam a edição
visual e seu seletor, margens de clique, movimento de reis, preservação do lado
a jogar e dos campos FEN, rei duplicado em f7, moldura assimétrica da página
565, probabilidades originais, cancelamento e nova tentativa de atualização,
pré-releases, falhas de consulta e inventário dos instaladores. Incluem revisão
fora da thread visual, resultados obsoletos, proteção de digitação, arraste,
cache da prévia, bolinhas indicativas e salvamento anterior à revisão.

A reavaliação de 341 diagramas com referência independente coincidiu em todas
as posições e 21.824 casas. A medição local da montagem da prévia passou de
44,45 ms para 0,90 ms; não mede o tempo total da edição. Resultados e limites
estão em [Avaliação do livro](AVALIACAO_LIVRO.md).

O diagnóstico `--self-test --report arquivo.json` executa os três modelos,
verifica os SVGs por hash e reconhece uma posição de referência dentro do
aplicativo empacotado, sem abrir janelas. O CI exige esse diagnóstico antes
de testar instalação, reinstalação no mesmo diretório e desinstalação.

## Execução

Os testes usam `unittest` e não dependem de pytest:

```powershell
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
```

O mesmo comando é executado pelo GitHub Actions antes de qualquer build. Uma
falha impede a criação do aplicativo e do instalador naquele job.

## Organização

### `tests/test_comparacao_filtro.py`

Valida os sete falsos positivos reais apresentados pelo usuário, a rejeição
pela rota de caixas de imagens PDF, a detecção do tabuleiro clássico, os 12
assets e seus hashes/licença, comparação com widgets Tk reais, atualização da
prévia ao editar, Forsyth inválida sem fallback enganoso, navegação sem
descartados, restauração persistente, PGN sem recortes excluídos e livros em
que todos os recortes foram descartados.

### `tests/test_padronizacao.py`

Valida desenho das peças, orientação a8/h1, equivalência português/inglês/FEN,
preservação de páginas, texto, links, metadados e pixels externos ao diagrama,
rotação com CropBox, quadriláteros inclinados, cancelamento, gravação atômica,
persistência do PDF original e dos cantos, compatibilidade com livros antigos
e rejeição de correspondências visuais ambíguas. Também verifica o fechamento
sem modal durante atualização, PGN com pendências independente da geração de
PDF e Forsyth abaixo do diagrama sem a mensagem de falso positivo.

### `tests/test_extrator.py`

Valida o detector, o fluxo de PDF e aspectos da distribuição:

- diferença entre tabuleiro e ruído;
- rejeição de tabela textual 8×8, círculos, peças ampliadas e texto;
- páginas com zero, um e vários diagramas;
- recorte sem legendas ou perguntas externas;
- correção de pequena inclinação;
- eliminação de duplicatas;
- diagramas pequenos e grandes, perspectiva e ordenação de cantos em losango;
- caixas raster com rotação de 0°, 90°, 180° e 270°, combinada com CropBox;
- duplicatas separadas por página e preservação de diagramas em molduras maiores;
- ordem da esquerda para a direita em linhas levemente desalinhadas;
- rejeição de imagem quadrada sem grade por padrão, aceitação apenas pela
  opção explícita de diagnóstico e rejeição de imagem raster retangular;
- cancelamento cooperativo na detecção e geração;
- PDF inválido, protegido, vazio e seletores cancelados;
- criação de uma página A4 por diagrama em uma integração sintética;
- versão semântica, editor, ícone e sugestão do nome de saída;
- formatação da estimativa de tempo;
- consulta da GitHub Release, rejeição de download adulterado e solicitação de
  reabertura após atualização.

### `tests/test_forsyth.py`

Valida notação, modelo, persistência, revisão automática e PDF anotado:

- convenção `a8` clara e leitura da fileira superior;
- conversão entre português e inglês;
- compactação, normalização e oito fileiras válidas;
- alertas de plausibilidade e possíveis falsos positivos;
- hash fixado do modelo e inferência das 64 casas;
- notação exata nas cinco fixtures públicas do fenshot, incluindo diagramas
  mostrados pela perspectiva das pretas e peças estilizadas;
- rejeição de probabilidades inválidas ou com dimensões trocadas;
- preservação da hipótese visual em confusões entre peão e cavalo;
- escolha do recorte sem deixar casas vazias mascararem peças incertas;
- avisos que identificam a coordenada da casa ambígua;
- substituição de referências manuais após nova edição da mesma imagem;
- gravação atômica e compatibilidade do rascunho;
- referências manuais vinculadas ao PDF;
- navegação e conclusão sem confirmação obrigatória;
- resposta imediata do checkbox de exclusão;
- referências separadas por paridade e classe;
- remoção do fundo hachurado;
- quantidade mínima, votação e vantagem exigidas para uma correção;
- pares conhecidos de confusão nos dois sentidos;
- precedência das edições manuais;
- correspondência entre anotação, diagrama e índice final;
- exclusão de itens marcados como não tabuleiro.

### `tests/test_ensemble.py`

Valida votação ponderada por casa, temperaturas, normalização, remapeamento de
classes, ordem espacial `a1…h8`, cores BGR, hashes dos três pesos, rejeição de
arquivos adulterados e de modelos duplicados, e avisos de divergência no
visualizador. A integração com a revisão pelo livro impede que casas disputadas
virem referências automáticas. `tests/test_forsyth.py` exige notação exata nas
cinco fixtures tanto com o modelo principal quanto com o ensemble.

Para comparar modelos e medir erros por casa, use `python tools/avaliar_ensemble.py`.
O protocolo e os resultados iniciais estão em [Ensemble](ENSEMBLE.md).

### `tests/test_edicao_rapida.py`

Valida execução da revisão fora da thread visual, descarte de resultados
antigos, preservação de digitação e edições manuais, espera das exportações,
cache da prévia, seleção da casa e arraste de peças/vazio. Testa as sete bolinhas
do recorte real `p0309-d05`, preservação das peças e das probabilidades dos
modelos, salvamento na biblioteca antes de abrir a revisão e reabertura sem
reconhecimento. As contagens distinguem posições OK, inválidas e incertas.

### `tests/test_biblioteca.py`

Valida a biblioteca interna e a exportação dos livros processados:

- persistência e reabertura de livros;
- renomeação, substituição e exclusão;
- edição das FENs e do lado a jogar;
- persistência do `Annotator`;
- exportação PGN com as tags `SetUp` e `FEN` completas.

Algumas funções legadas de transformação continuam testadas mesmo sem controle
correspondente na interface. Isso preserva compatibilidade dos dados antigos e
evita que uma futura migração interprete um rascunho de forma incorreta.

## Imagens sintéticas

Os testes constroem tabuleiros e páginas em memória para controlar exatamente a
posição, rotação, quantidade e presença de texto. O PDF de integração também é
gerado temporariamente durante o teste e removido ao final. Dessa forma o
repositório não precisa distribuir livros completos nem depender de material
com direitos autorais.

Fixtures públicas pequenas são mantidas apenas quando sua origem e licença são
conhecidas. O modelo de terceiros é acompanhado de sua licença e de um hash
verificado pelo teste.

## O que os testes não substituem

Na revisão de 9 de outubro de 2026, a notação completa correta nas cinco
fixtures públicas passou de 3/5 para 5/5 após o ajuste dos contornos. O teste
agora exige a posição exata para todas as cinco imagens, inclusive quando uma
sugestão estiver pendente de revisão. Esse conjunto pequeno é uma regressão
reproduzível, não uma estimativa de acurácia em livros digitalizados antigos.

Visão computacional pode passar nos casos sintéticos e ainda falhar em um estilo
de impressão não representado. Antes de uma release, também é necessário:

1. testar um conjunto real com páginas sem diagrama, um e vários diagramas;
2. comparar a contagem com o índice conhecido do livro;
3. inspecionar diagramas de baixa qualidade e falsos positivos;
4. avaliar separadamente as confusões `P/N`, `p/n`, `p/b` e `B/Q`;
5. confirmar que nenhuma correção automática piorou uma casa antes correta;
6. abrir o PDF final e conferir ordem, corte, textos selecionáveis e índice;
7. instalar o Setup em uma máquina Windows 64 bits sem Python;
8. testar atualização sobre uma versão anterior e desinstalação.

## Critério conservador do Forsyth

Uma sugestão marcada internamente como confiável não deve conter uma casa
incorreta no benchmark adotado para publicação. Correções automáticas devem
buscar precisão mínima de 99%; casos sem evidência suficiente ficam inalterados.
Essas metas priorizam não introduzir erros, mesmo que algumas confusões deixem
de ser corrigidas.

Ao acrescentar um novo estilo de livro, o ideal é transformar o menor exemplo
reproduzível em fixture ou gerar uma aproximação sintética. O teste deve falhar
antes da correção e passar depois dela, evitando regressões silenciosas.

## Verificações rápidas de manutenção

O teste real de `TERCEIRA_VERSAO_unida.pdf`, com 601 páginas, pode ser repetido
com `tools/avaliar_livro.py`. O [guia de avaliação](AVALIACAO_LIVRO.md) descreve
os recortes e a revisão HTML, a referência textual para duas fontes de xadrez
e as limitações das métricas sem anotação manual do livro inteiro.
`tests/test_avaliacao_livro.py` verifica a orientação, os erros por casa, a
separação entre peças e casas vazias, a decodificação dos glifos e a rejeição
de anotações pertencentes a outro conjunto de recortes.

Para alterações apenas em documentação:

```powershell
git diff --check
```

Para alterações Python, além da suíte completa, pode-se fazer uma verificação
sintática sem iniciar a interface:

```powershell
python -m compileall -q .
```

Pastas de livros locais, PDFs produzidos, `build/`, `dist/` e `release/` não
devem ser versionados. O `.gitignore` mantém esses artefatos fora do histórico.
