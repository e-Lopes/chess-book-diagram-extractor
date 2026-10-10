# Diagramas padronizados a partir de Forsyth

Na revisão inicial e no editor da biblioteca, **Lado a lado** mostra
simultaneamente o recorte extraído e o tabuleiro reconstruído, com títulos
separados. **Original / Padronizado** permite ampliar cada imagem sozinha.
Uma seta simples liga **Original → Reconstruído pela Forsyth**.
Clicar na imagem reconstruída abre um seletor visual das doze peças e de
**Casa vazia**. O clique considera o tamanho real da imagem centralizada,
ignorando as margens vazias. Escolher uma peça atualiza a posição, a prévia e o
salvamento da revisão/biblioteca. Colocar um rei move o existente da mesma cor.
A validação continua exigindo os dois reis para exportar aquela posição.
Alterações manuais são protegidas da revisão automática do livro.
Uma borda azul indica a casa selecionada. A paleta abaixo das imagens permite
arrastar peças ou vazio até a casa de destino; soltar fora do tabuleiro não
altera a posição. O seletor por clique continua disponível.

`renderizar_previa` monta a imagem de 800×800 com um cache limitado às 26
combinações de peça/vazio e paridade. A foto original e as versões redimensionadas
também são reutilizadas quando possível. A revisão do livro ocorre em segundo
plano com indicador animado; exportações aguardam sua conclusão. Na biblioteca,
edições próximas são salvas juntas e a saída do diagrama força essa gravação.
O cache da prévia não altera o renderer completo usado na exportação do PDF.
**Reavaliar imagem** substitui a posição atual pelo novo reconhecimento; está
disponível também para recuperar recortes antigos.
Uma Forsyth inválida mostra uma indicação na reconstrução, sem reutilizar
a foto original no painel padronizado. A posição completa
com `w/b` fica abaixo da imagem e pode ser copiada. **Brancas / Pretas** define
o lado a jogar sem modificar a orientação visual do tabuleiro.

**Exportar livro padronizado** salva uma cópia do livro com cada diagrama
substituído no seu local original. A exportação usa as posições editadas no
momento do clique, executa em uma thread e mostra progresso e cancelamento.
Avisos de reconhecimento não impedem a saída. Posições inválidas, recortes
marcados para exclusão e localizações não confirmadas não são substituídos;
o resumo informa a quantidade mantida.

## Desenho e coordenadas

`tabuleiros_padronizados.py` usa as doze peças clássicas Cburnett de Wikimedia
Commons, sob a opção BSD de 3 cláusulas. Os SVGs originais são mantidos em
`assets/pieces/cburnett`, com fontes e SHA-256 registrados em `manifest.json`.
Consulte [avisos de terceiros](../THIRD_PARTY_NOTICES.md) e a
[licença das peças](../licenses/cburnett-BSD-3-Clause.txt).
O aplicativo não precisa de fontes, serviços de imagem ou rede para desenhar.
`renderizar_tabuleiro` aceita notação portuguesa, inglesa, o sufixo opcional
`w/b` e FEN com seis campos. A imagem tem `a8` clara e lê as oito fileiras
de cima para baixo. O lado a jogar não altera o desenho.

O detector guarda `quadro_pdf` no `Candidato`: os quatro cantos da página
renderizada, em pontos PDF (pixels × 72 / DPI). Essa localização continua
disponível ao reler o PDF dos recortes e na biblioteca. Antes de inserir a
imagem, a exportação converte os cantos usando `Page.derotation_matrix`.
A ordem dos cantos é preservada para manter a orientação em páginas rotacionadas.

O tabuleiro é deformado por homografia até o quadrilátero original. A imagem
PNG opaca recebe clipping vetorial no seu próprio stream PDF. Isso evita que
uma máscara de transparência mude a composição e o antialias do texto no
restante da página. Páginas, textos selecionáveis, links e metadados são
preservados. A saída usa arquivo temporário e substituição atômica. Escolher
o próprio arquivo de origem como destino é recusado.

## Biblioteca

Novos processamentos guardam `original.pdf` junto de `diagramas.pdf` e dos
metadados. Assim, a exportação funciona mesmo que o PDF escolhido durante a
extração seja movido ou apagado. O armazenamento passa a incluir uma cópia
adicional do livro inteiro. Editar e renomear preserva o original e os cantos.

Recortes antigos sem grade são ocultos por padrão, preservando imagens e
posições. **Mostrar recortes descartados** permite conferir a classificação;
desmarcar **Não é um tabuleiro — descartar** restaura o recorte. A exclusão
fica salva e é respeitada nas exportações, incluindo posições válidas que
tenham sido atribuídas a uma foto ou texto por engano.

O formato anterior continua compatível, com `quadro_pdf` vazio e original
ausente. Para padronizar um livro antigo, a interface solicita seu PDF original
e compara os recortes com novas detecções nas páginas correspondentes. A
correlação precisa atingir 0,92, superar a segunda opção por pelo menos 0,04
e produzir correspondência única. Diagramas idênticos na mesma página não
recebem atribuição automática de posições editadas. Nessas situações, faça
uma nova extração para guardar localizações explícitas.

## Uso por código ou linha de comando

```python
from tabuleiros_padronizados import renderizar_tabuleiro
imagem_bgr = renderizar_tabuleiro("4r3/8/8/8/8/8/8/4R3 b", idioma="pt")
```

```powershell
python tools/padronizar_pdf.py livro.pdf livro_padronizado.pdf --diagramas posicoes.json --idioma en
```

O JSON deve conter `diagramas`, com `pagina` (a partir de 1), `posicao` e
`quadro_pdf` (quatro pontos: superior esquerdo, superior direito, inferior
direito, inferior esquerdo, na página renderizada).

## Verificação no livro fornecido

Em `build/filtro-comparacao/TERCEIRA_VERSAO_pecas_classicas_amostra.pdf`, foram
substituídos os 341 diagramas que possuem referência independente obtida das
fontes ChessMerida e DiagramTTFritz. Os demais diagramas permanecem originais:
esta é uma demonstração parcial, não uma alegação de revisão completa do livro.
Foram preservadas as 601 páginas, seus tamanhos, rotações e todos os textos
selecionáveis. O SHA-256 do livro original permaneceu idêntico. O relatório
está em `build/filtro-comparacao/verificacao.json`; imagens antes/depois de páginas
16, 85, 308 e 405 permitem conferir estilos diferentes.
