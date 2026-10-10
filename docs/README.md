# Documentação técnica

Esta documentação descreve como o **Chess Book Diagram Extractor** funciona
internamente e registra as principais decisões tomadas durante seu
desenvolvimento. O [README principal](../README.md) continua sendo o guia de
instalação e uso para o público final.

## Visão geral do sistema

O aplicativo recebe um livro em PDF, localiza tabuleiros 8×8, gera um primeiro
PDF apenas com os recortes e, quando solicitado, reconhece e apresenta as
posições em notação Forsyth antes de produzir o documento anotado.

```mermaid
flowchart LR
    A[Livro PDF] --> B[Renderização das páginas]
    B --> C[Detecção dos tabuleiros]
    C --> D[PDF das extrações]
    D --> E{Incluir Forsyth?}
    E -- Não --> F[Resultado concluído]
    E -- Sim --> G[Reconhecimento ONNX]
    G --> H[Comparação dentro do livro]
    H --> K[Salva livro e posições na biblioteca]
    K --> I[Visualizador de posições]
    I --> K
    I --> J[PDF anotado e índice Forsyth]
```

O PDF original nunca é modificado. O processamento visual e o reconhecimento
das peças são locais; a rede é usada somente pelo atualizador.

## Guias

- [Arquitetura](ARQUITETURA.md): módulos, fluxo de execução, threads,
  persistência e tratamento de erros.
- [Algoritmos](ALGORITMOS.md): detecção 8×8, reconhecimento Forsyth e revisão
  automática baseada nas peças do próprio livro.
- [Ensemble](ENSEMBLE.md): três modelos locais, votação por casa, divergências,
  fontes dos pesos e avaliação comparativa.
- [Avaliação de livros](AVALIACAO_LIVRO.md): teste de PDFs completos com estilos
  variados, referências independentes e revisão de erros por página e casa.
- [Padronização dos diagramas](PADRONIZACAO.md): desenho a partir de Forsyth,
  sobreposição no livro original e compatibilidade com a biblioteca antiga.
- [Distribuição para Windows](DISTRIBUICAO_WINDOWS.md): dependências, build,
  instalador, releases, atualizações e assinatura.
- [Testes e qualidade](TESTES.md): cobertura automatizada, fixtures, integração
  sintética e validações antes de publicar.
- [Decisões técnicas](DECISOES_TECNICAS.md): contexto, alternativas e
  consequências das escolhas mais importantes.

## Mapa do repositório

| Caminho | Responsabilidade |
|---|---|
| `interface_windows.py` | Janela principal, coordenação das tarefas e atualização da interface |
| `extrair_tabuleiros_pdf.py` | Renderização, detecção, recorte e geração dos PDFs |
| `notacao_forsyth.py` | Notação, inferência ONNX, revisão automática e persistência |
| `reconhecimento_ensemble.py` | Contratos, pré-processamento dos modelos e combinação das probabilidades |
| `revisor_forsyth.py` | Visualizador e edição opcional das posições reconhecidas |
| `visualizacao_diagramas.py` | Comparação lado a lado entre o recorte original e a reconstrução |
| `alinhamento_tabuleiro.py` | Localização da grade interna e remoção de moldura assimétrica |
| `restricoes_reconhecimento.py` | Eleição conjunta de exatamente um rei de cada cor |
| `reconhecimento_ui.py` | Reavaliação de uma imagem sem bloquear o Tkinter |
| `marcadores_diagrama.py` | Bolinhas indicativas tratadas como casas vazias |
| `revisao_assincrona.py` | Revisão do livro em segundo plano, com proteção de edições |
| `biblioteca_livros.py` | Persistência, contagens de revisão e exportação PGN |
| `verificacao_distribuicao.py` | Diagnóstico dos recursos e modelos dentro do executável |
| `tabuleiros_padronizados.py` | Desenho das peças e sobreposição restrita aos diagramas |
| `exportacao_padronizada_ui.py` | Exportação com progresso e cancelamento na revisão e biblioteca |
| `autoupdate.py` | Consulta, download, validação e início de uma atualização |
| `version.py` | Versão e identificação do repositório |
| `models/` | Três modelos ONNX e catálogo de pesos do ensemble |
| `tools/` | Conversão reproduzível de modelos e avaliação comparativa |
| `icon/` | Ícones usados na janela, executável, instalador e README |
| `packaging/` | Metadados de versão, ícone e script do Inno Setup |
| `tests/` | Testes automatizados e fixtures públicas |
| `.github/workflows/` | Build e publicação automatizados no GitHub Actions |

## Versão 0.4.1

[Notas da versão](RELEASE_NOTES_v0.4.1.md) descrevem a edição por clique/arraste,
o salvamento anterior à revisão e as contagens da biblioteca. A versão passou
em 165 testes locais; o subconjunto de 341 diagramas com referência tipográfica
foi reconhecido exatamente. O protocolo e seus limites estão em
[avaliação do livro](AVALIACAO_LIVRO.md).

## Princípios do projeto

- O livro permanece no computador do usuário.
- Perder um tabuleiro é mais prejudicial que apresentar um candidato extra que
  possa ser excluído no visualizador.
- Uma correção automática de peça só é aceita com evidência forte; na dúvida,
  a classificação original é preservada.
- A interface nunca deve ficar bloqueada por processamento pesado.
- Arquivos finais e rascunhos importantes são gravados de forma atômica sempre
  que possível.
- O instalador deve funcionar em Windows 10 e 11 de 64 bits sem exigir uma
  instalação prévia de Python.
