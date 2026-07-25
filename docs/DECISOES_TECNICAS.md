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

## Priorizar recuperação de diagramas

**Contexto:** em um livro de problemas, faltar um exercício é pior que incluir
um candidato extra que o usuário consiga excluir.

**Decisão:** aceitar confiança moderada e usar uma recuperação mais sensível
somente quando o próprio livro demonstra um padrão alternado confiável.

**Consequência:** aumenta a cobertura sem liberar o limiar em todas as páginas.
Ainda pode haver falsos positivos, tratados pela marcação “Não é um
tabuleiro/diagrama”.

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

