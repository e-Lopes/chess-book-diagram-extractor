# Arquitetura

## Componentes

### Interface e coordenação

`interface_windows.py` é o ponto de entrada do aplicativo empacotado. A classe
`InterfaceExtrator` constrói a interface com Tkinter e ttkbootstrap, mantém o
estado da operação atual e coordena os módulos especializados. Ela não contém
os algoritmos de visão computacional.

A janela principal é responsável por:

- selecionar o PDF de entrada e sugerir `<nome>_diagramas.pdf`;
- guardar as preferências de abertura automática, uso de Forsyth e idioma;
- iniciar e cancelar a operação;
- traduzir eventos de progresso em percentual e estimativa de tempo;
- abrir o visualizador após a criação do PDF das extrações;
- consultar atualizações sem bloquear a interface.

### Extração

`extrair_tabuleiros_pdf.py` concentra o pipeline independente da interface. Os
principais contratos são:

- `Candidato`: página, quadrilátero, imagem retificada e confiança;
- `AnotacaoSaida`: texto e metadados colocados no PDF final;
- `ResultadoExtracao`: caminho, número de páginas e candidatos encontrados;
- `detectar_no_pdf()`: percorre e analisa o livro;
- `criar_pdf_a4()`: compõe uma página A4 por diagrama;
- `processar_pdf()`: fachada do fluxo simples de extração.

As funções continuam utilizáveis sem a interface gráfica, o que permite testes
isolados e futuras integrações.

### Reconhecimento e revisão automática

`notacao_forsyth.py` reúne três responsabilidades relacionadas:

1. conversão, expansão, compactação e validação da posição Forsyth;
2. classificação das 64 casas pelo `ReconhecedorForsyth`;
3. comparação conservadora entre peças do mesmo livro pelo
   `RevisorAutomaticoLivro`.

`DadosCasa` preserva a imagem normalizada, paridade, probabilidades, top-3,
margem e classe original de cada casa. `ResultadoReconhecimento` mantém essas
informações junto da posição sugerida. Essa estrutura evita perder dados que a
segunda passagem precisa para tomar decisões.

### Visualizador

`revisor_forsyth.py` implementa `JanelaRevisaoForsyth`. O visualizador percorre
o PDF já extraído, mostra um diagrama por vez e permite:

- navegar para o primeiro, anterior, próximo ou último diagrama;
- consultar ou editar a posição;
- marcar um recorte como não sendo tabuleiro;
- salvar as notações no PDF final.

O visualizador é deliberadamente uma etapa de inspeção, não um formulário que
obriga a confirmação de centenas de posições. Ao fechar antes de concluir, o
estado é salvo para possível retomada.

### Atualização

`autoupdate.py` consulta a última GitHub Release, compara versões semânticas,
localiza o instalador com nome versionado, valida origem, tamanho e SHA-256 e só
então o inicia em modo silencioso. O módulo não decide sozinho instalar: a
confirmação é feita pela interface.

## Fluxo de uma execução

1. A interface valida entrada e saída e cria um evento de cancelamento.
2. Uma thread de trabalho chama `detectar_no_pdf()`.
3. Cada página é renderizada pelo PyMuPDF a 240 DPI e analisada pelo OpenCV.
4. Os candidatos aceitos são ordenados por página e posição.
5. `criar_pdf_a4()` grava atomicamente o PDF das extrações.
6. Sem Forsyth, o fluxo termina nesse arquivo.
7. Com Forsyth, os diagramas são relidos do PDF das extrações. Isso garante que
   reconhecimento e visualização usem exatamente a imagem entregue ao usuário.
8. O ONNX Runtime classifica as 64 casas de cada diagrama.
9. Uma segunda passagem cria referências do próprio livro e revê apenas casos
   ambíguos sob critérios conservadores.
10. O visualizador é aberto na thread da interface.
11. Ao concluir, uma thread gera o PDF anotado, omite itens marcados como falsos
    positivos e acrescenta o índice Forsyth.
12. Depois de uma gravação bem-sucedida, o rascunho é removido.

## Concorrência e responsividade

Tkinter exige que widgets sejam manipulados pela thread principal. Por isso,
detecção, reconhecimento, geração do PDF, consulta e download de atualizações
rodam em threads de trabalho. Essas threads publicam mensagens em uma fila; a
janela consulta a fila periodicamente com `after()` e atualiza os widgets.

O cancelamento é cooperativo. Um `threading.Event` é consultado entre páginas e
etapas relevantes. Quando acionado, o código lança `ExtracaoCancelada`, remove
arquivos temporários e restaura a interface. Não se encerra uma thread à força,
pois isso poderia deixar um PDF parcial ou recursos nativos em estado inválido.

Operações caras provocadas por controles também são adiadas. Por exemplo,
marcar “Não é um tabuleiro/diagrama” apenas invalida a biblioteca de referências;
os descritores HOG são reconstruídos na próxima revisão, evitando travar o Tk.

## Dados locais

Os dados ficam em `%LOCALAPPDATA%\ChessBookDiagramExtractor`:

| Item | Finalidade |
|---|---|
| `settings.json` | Preferências da interface |
| `app.log` | Diagnóstico de falhas e eventos relevantes |
| `drafts/<impressão-digital>.json` | Retomada do visualizador |
| `learning/<impressão-digital>.json` | Referências criadas por edições daquele livro |

A impressão digital vincula aprendizado e rascunho ao PDF correspondente. Não
há compartilhamento de exemplos entre livros. Referências de itens excluídos
são ignoradas e removidas.

Rascunhos são escritos em um arquivo temporário e substituídos somente após a
serialização completa. O mesmo princípio é usado na criação dos PDFs, reduzindo
o risco de deixar um resultado corrompido se houver erro ou cancelamento.

## Recursos no ambiente empacotado

`caminho_recurso()` resolve arquivos tanto durante o desenvolvimento quanto no
diretório temporário `_MEIPASS` criado pelo PyInstaller. Assim, ícones, modelo e
licenças são encontrados pelo mesmo código nas duas formas de execução.

## Erros observáveis

Falhas previstas são convertidas em mensagens compreensíveis, como PDF
inválido, protegido, sem diagramas ou atualização inconsistente. Detalhes
técnicos permanecem em `app.log`. O código não usa a grande caixa de logs na
interface porque informações de depuração não ajudam o fluxo normal do usuário.
