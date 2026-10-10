# Decisões técnicas

Este documento registra decisões que não são evidentes apenas pela leitura do
código. Cada item apresenta o problema, a escolha atual e sua consequência.

## Processamento totalmente local

**Contexto:** livros podem ter direitos autorais, dados pessoais ou não poderem
ser enviados a serviços externos.

**Decisão:** renderização, detecção e reconhecimento são executados localmente.
A internet é usada apenas para atualizações.

**Consequência:** há privacidade, funcionamento offline e custo zero por página,
mas o instalador inclui bibliotecas nativas e o modelo, ficando maior.

## OpenCV para localizar tabuleiros

**Contexto:** o alvo possui uma geometria muito específica: quadrado, borda e
alternância periódica 8×8.

**Decisão:** usar características geométricas e visuais interpretáveis em vez
de um detector treinado.

**Consequência:** não é necessário manter um conjunto de treinamento nem um
segundo modelo. Os limiares são testáveis e ajustáveis, mas digitalizações fora
do padrão podem exigir novas heurísticas.

## Exigir evidência da grade na extração normal

**Contexto:** em um livro de problemas, faltar um exercício é pior que incluir
um candidato extra que o usuário consiga excluir.

**Decisão:** usar a forma quadrada para gerar candidatos e exigir evidência
de alternância 8×8 para aceitá-los. `aceitar_quadrados=True` fica disponível
apenas para diagnóstico por código.

**Consequência:** fotos, mapas, letras e texto quadrado deixam de passar só
pelo formato. Diagramas degradados podem exigir inspeção adicional; recortes
aceitos por engano ainda podem ser descartados manualmente.

## Gerar o PDF de extrações antes da notação

**Contexto:** detectar tabuleiros e reconhecer peças têm ritmos, falhas e usos
independentes.

**Decisão:** salvar primeiro o PDF das extrações e usar esse arquivo como fonte
da etapa Forsyth.

**Consequência:** o usuário obtém o resultado principal mesmo se não quiser ou
interromper a notação. O visualizador também mostra exatamente os recortes que
serão usados, sem diferença entre coordenadas do livro e do documento final.

## ONNX fixado e verificado

**Contexto:** baixar um modelo na primeira execução comprometeria o uso offline,
a reprodutibilidade e a segurança da cadeia de distribuição.

**Decisão:** incluir o modelo do fenshot, fixar seu commit e validar o SHA-256
antes da inferência.

**Consequência:** todos usam o mesmo modelo e uma alteração acidental é detectada.
Atualizar o modelo exige uma decisão explícita, novos testes e atualização dos
avisos de licença.

## Ensemble de três classificadores locais

**Contexto:** redes treinadas com estilos diferentes podem oferecer hipóteses
complementares para uma mesma casa. Probabilidades altas também podem estar
erradas em estilos fora do treinamento.

**Decisão:** combinar fenshot, Linrock e TensorFlow Chessbot em ONNX com os
pesos iniciais 60/30/10, preservando o preparo específico de cada rede. Registrar
as previsões individuais e sinalizar divergências fortes. Todas as casas usam
a mesma hipótese de recorte antes da combinação.

**Consequência:** o instalador inclui aproximadamente 17,5 MB adicionais de
pesos e o reconhecimento faz mais inferências. A avaliação atual preserva
5/5 posições exatas; não demonstra ganho sobre o fenshot isolado. Os pesos e
temperaturas ainda precisam de calibração em livros reais. Casos disputados
não alimentam referências automáticas. Fontes, licenças e protocolo estão em
[Ensemble](ENSEMBLE.md).

## Não usar uma VLM

**Contexto:** uma VLM poderia interpretar alguns casos ambíguos, mas exigiria
API ou um modelo local muito maior.

**Decisão:** não incluir VLM nesta etapa. Reutilizar exemplos confiáveis do
próprio livro com OpenCV e as probabilidades ONNX.

**Consequência:** o aplicativo continua offline, leve, sem chave, cobrança ou
envio de imagens. A revisão visual pode não resolver estilos com poucos exemplos
confiáveis, mas seu resultado é determinístico e auditável.

## Comparar apenas a mesma cor de casa

**Contexto:** o hachurado ou preenchimento de uma casa escura interfere na
silhueta. A mesma peça pode parecer muito diferente em casas claras e escuras.

**Decisão:** manter fundos e referências separados por paridade, considerando
`a8` — canto superior esquerdo — uma casa clara.

**Consequência:** há menos referências disponíveis em cada grupo, porém se evita
uma fonte importante de correções erradas.

## Revisão automática conservadora

**Contexto:** corrigir uma previsão correta é mais grave que deixar uma casa
duvidosa inalterada.

**Decisão:** exigir referência forte, top-3 original, votação unânime entre
vizinhos, similaridade adequada, vantagem mínima e não piora da plausibilidade.

**Consequência:** a precisão tem prioridade sobre a quantidade de mudanças.
Casos sem evidência suficiente permanecem com a classe original e podem ser
editados no visualizador.

## Um alfabeto interno, dois alfabetos externos

**Contexto:** o usuário pode preferir Forsyth em português ou inglês.

**Decisão:** guardar classes e referências internamente em inglês e converter
somente nas fronteiras da interface e do PDF.

**Consequência:** todas as regras de comparação, plausibilidade e aprendizado
são únicas. Trocar o idioma não invalida os exemplos aprendidos.

## Visualizador sem confirmação obrigatória

**Contexto:** livros podem conter centenas de diagramas. Exigir confirmação de
cada posição tornaria o recurso impraticável.

**Decisão:** tratar a tela como visualizador, permitindo navegação, edição
opcional e exclusão de candidatos. Métricas de depuração e longas listas de
ambiguidades não são exibidas no fluxo normal.

**Consequência:** a experiência permanece rápida. Desenvolvedores encontram
detalhes nos dados internos, testes e log, enquanto o usuário vê apenas ações
relevantes.

## Aprendizado limitado ao PDF

**Contexto:** uma correção manual é uma referência excelente para aquele livro,
mas estilos tipográficos podem mudar completamente em outro.

**Decisão:** persistir referências pelo hash do PDF e nunca compartilhá-las
automaticamente entre livros.

**Consequência:** uma correção não contamina obras diferentes. Se o arquivo
mudar, sua impressão digital também muda e o aprendizado anterior não é aplicado.

## Threads de trabalho e cancelamento cooperativo

**Contexto:** renderização, ONNX e escrita de PDFs podem levar minutos, enquanto
Tkinter precisa manter seu loop livre.

**Decisão:** executar tarefas demoradas fora da thread principal, comunicar por
fila e cancelar por evento verificado em pontos seguros.

**Consequência:** a janela continua respondendo e os arquivos podem ser
finalizados ou removidos corretamente. O cancelamento pode levar alguns
instantes se uma operação nativa indivisível estiver em andamento.

## Edição imediata e revisão do livro em segundo plano

**Contexto:** revisar todos os diagramas antes de repintar uma casa tornava
trocas de peças e vazio lentas em livros grandes.

**Decisão:** reutilizar imagens das casas, agrupar edições próximas e revisar
cópias dos estados fora da thread visual. Aplicar apenas resultados atuais,
preservando intervenções manuais e mostrando progresso discreto.

**Consequência:** editar não espera a revisão completa; exportar aguarda a
última revisão sem bloquear a interface. A montagem da prévia medida localmente
caiu de 44,45 ms para 0,90 ms. Essa medição cobre a montagem da imagem, não o
tempo total de clique, validação, gravação ou exportação.

## Salvar antes da revisão e tornar pendências visíveis

**Contexto:** fechar a revisão inicial deixava o livro fora da biblioteca,
apesar de existir um PDF extraído e um rascunho.

**Decisão:** persistir o livro assim que o reconhecimento termina e salvar
correções também nos metadados da biblioteca. Contar posições inválidas e
reconhecimentos incertos em **Ajustar / conferir**, oferecendo confirmação manual.

**Consequência:** o usuário retoma pela biblioteca sem processar novamente.
**OK** significa validação e confiança ou conferência manual; não é garantia
de correção de toda peça. Recortes descartados não entram nessas contagens.

## Separar bolinhas de peças

**Contexto:** oito diagramas de referência tinham 40 casas vazias marcadas
com pontos que os modelos confundiam com peças.

**Decisão:** identificar apenas componentes pequenos, isolados e circulares,
tratá-los como vazio na eleição e preservá-los na revisão automática. Manter
os votos originais para diagnóstico.

**Consequência:** a avaliação da v0.4.1 passou a 341/341 posições exatas no
subconjunto tipográfico. Isso não representa acurácia medida em todo o livro
nem comprova vantagem do ensemble sobre modelos individuais reavaliados.

## Escrita atômica

**Contexto:** fechar o aplicativo, cancelar ou ficar sem espaço durante uma
gravação não deve destruir um resultado anterior válido.

**Decisão:** escrever PDFs, downloads e rascunhos em arquivos temporários antes
de substituir o destino.

**Consequência:** podem existir temporários durante a operação, mas o nome final
só representa um arquivo concluído e validado.

## PyInstaller `onedir` com instalador único

**Contexto:** um único EXE PyInstaller seria conveniente, porém extrair muitas
DLLs e o runtime ONNX a cada abertura aumenta latência e complexidade.

**Decisão:** produzir uma pasta autocontida com PyInstaller e empacotá-la em um
único Setup pelo Inno Setup.

**Consequência:** o download continua simples e o aplicativo instalado abre sem
extração temporária completa. O atualizador substitui a instalação por meio do
mesmo `AppId`.

## Atualização pela GitHub Release com SHA-256

**Contexto:** o usuário não deve reinstalar manualmente a cada versão e um
download corrompido ou trocado não pode ser executado.

**Decisão:** consultar apenas a Release mais recente do repositório configurado,
validar nome, URL, tamanho e digest antes de iniciar o instalador.

**Consequência:** a publicação precisa seguir a convenção de tags e nomes. O
SHA-256 garante integridade, enquanto a confiança do editor no Windows depende
separadamente da assinatura Authenticode.

## Substituição dos diagramas em uma cópia do livro

**Contexto:** uma posição revisada permite reconstruir um tabuleiro limpo sem
alterar o texto e o restante da página do livro.

**Decisão:** guardar o PDF original e os cantos detectados em pontos PDF na
biblioteca; desenhar com as peças clássicas Cburnett em SVG e sobrepor o tabuleiro na cópia do
livro. Uma homografia respeita os cantos e um clipping vetorial restringe a
imagem ao quadrilátero. A página inteira não é rasterizada nem redigida.

**Validação:** testes com rotação 0/90/180/270, CropBox, caixas inclinadas,
preservação de texto, links e pixels externos, gravação atômica e cancelamento.
No livro de 601 páginas, uma amostra substituiu 341 diagramas com referência
independente e preservou todos os textos. A interface oferece prévia e exportação.

**Compatibilidade:** livros antigos continuam abrindo. Quando faltam original
ou cantos, a exportação solicita o PDF e faz correspondência visual por página.
Correspondências ambíguas são omitidas, preservando a região original.

## Exigir grade e oferecer comparação visual

**Problema:** `aceitar_quadrados=True` admitia textos, mapas e retratos mesmo
com pontuação estrutural zero. A prévia individual dificultava a comparação
de cada casa e podia exibir a foto original quando a Forsyth era inválida.

**Decisão:** exigir evidência 8×8 no fluxo normal; oferecer comparação lado a
lado como prévia padrão, com indicação explícita quando a posição não pode
ser desenhada. Nos livros antigos, ocultar recortes descartados sem apagar
dados e guardar a escolha manual de restaurar ou descartar.

**Resultado:** no PDF de 601 páginas, 205 recortes removidos, 594 mantidos e
341/341 referências independentes preservadas. Os sete exemplos apresentados
pelo usuário viraram fixtures de regressão. O desenho usa os SVGs Cburnett
obtidos diretamente de Wikimedia Commons sob a opção BSD-3-Clause, com
arquivos originais, hashes, atribuição e licença incluídos na distribuição.
