# Testes e qualidade

## Execução

Os testes usam `unittest` e não dependem de pytest:

```powershell
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
```

O mesmo comando é executado pelo GitHub Actions antes de qualquer build. Uma
falha impede a criação do aplicativo e do instalador naquele job.

## Organização

### `tests/test_extrator.py`

Valida o detector, o fluxo de PDF e aspectos da distribuição:

- diferença entre tabuleiro e ruído;
- rejeição de tabela textual 8×8, círculos, peças ampliadas e texto;
- páginas com zero, um e vários diagramas;
- recorte sem legendas ou perguntas externas;
- correção de pequena inclinação;
- eliminação de duplicatas;
- recuperação de página incompleta no padrão alternado;
- cancelamento cooperativo na detecção e geração;
- PDF inválido, protegido, vazio e seletores cancelados;
- criação de uma página A4 por diagrama em uma integração sintética;
- versão semântica, editor, ícone e sugestão do nome de saída;
- formatação da estimativa de tempo;
- consulta da GitHub Release e rejeição de download adulterado.

### `tests/test_forsyth.py`

Valida notação, modelo, persistência, revisão automática e PDF anotado:

- convenção `a8` clara e leitura da fileira superior;
- conversão entre português e inglês;
- compactação, normalização e oito fileiras válidas;
- alertas de plausibilidade e possíveis falsos positivos;
- hash fixado do modelo e inferência das 64 casas;
- fixtures públicas do fenshot;
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

