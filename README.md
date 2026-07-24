# Chess Book Diagram Extractor

[![Baixar para Windows](https://img.shields.io/badge/Baixar_para_Windows-Chess_Book_Diagram_Extractor-2457A6?style=for-the-badge&logo=windows11&logoColor=white)](https://github.com/e-Lopes/chess-book-diagram-extractor/releases/latest/download/ChessBookDiagramExtractor-Setup.exe)

Aplicativo gratuito para Windows que encontra automaticamente diagramas de
tabuleiros 8×8 em livros de xadrez em PDF. O resultado é um novo PDF A4, com
um tabuleiro centralizado por página, pronto para imprimir ou estudar.

<p align="center">
  <img src="icon/icon.png" alt="Ícone do Chess Book Diagram Extractor" width="128">
</p>

## Recursos

- Detecta páginas com zero, um ou vários diagramas.
- Recorta as 64 casas, as peças e a borda imediata do tabuleiro.
- Corrige pequenas inclinações e elimina detecções duplicadas.
- Filtra ilustrações, peças isoladas e outros falsos positivos comuns.
- Preserva a ordem em que os diagramas aparecem no livro.
- Cria um PDF A4 branco com um diagrama centralizado por página.
- Verifica novas versões no GitHub e valida o SHA-256 antes de atualizar.
- Inclui desinstalador e não exige que o usuário instale Python.

## Instalar no Windows

1. Clique em **Baixar para Windows** no início desta página.
2. Salve e execute `ChessBookDiagramExtractor-Setup.exe`.
3. Siga as instruções do instalador.
4. Abra **Chess Book Diagram Extractor** pelo menu Iniciar.

O programa é instalado somente para o usuário atual. Enquanto o projeto não
possuir um certificado de assinatura de código, o Windows SmartScreen pode
mostrar um aviso na primeira execução do instalador.

## Como usar

1. Clique em **Selecionar...** e escolha o livro em PDF.
2. Escolha onde salvar o arquivo sugerido `Diagramas_Livro.pdf`.
3. Clique em **Extrair diagramas**.
4. Acompanhe o progresso e abra a pasta do resultado ao terminar.

O livro original não é alterado.

## Atualizações automáticas

Ao iniciar, o aplicativo consulta a release mais recente deste repositório.
Quando houver uma nova versão, ele pede confirmação antes de baixar qualquer
arquivo. O instalador baixado só é executado depois que seu hash SHA-256 for
comparado com o valor publicado pelo GitHub.

Também é possível clicar em **Verificar atualizações** a qualquer momento.

## Desinstalar

Use uma destas opções:

- clique em **Desinstalar programa** dentro do aplicativo;
- abra **Desinstalar Chess Book Diagram Extractor** no menu Iniciar;
- use **Configurações > Aplicativos > Aplicativos instalados** no Windows.

O Editor exibido pelo Windows é **E-Lopes**.

## Segurança e transparência

O código-fonte, o histórico de versões e o processo automatizado de build são
públicos. Consulte a [Política de Privacidade](PRIVACY.md) e a
[Code signing policy](CODE_SIGNING_POLICY.md).

O projeto solicitou a assinatura gratuita fornecida por
[SignPath.io](https://signpath.io/), com certificado da
[SignPath Foundation](https://signpath.org/). Versões publicadas antes da
conclusão dessa integração podem não possuir assinatura digital.

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

## Limitações conhecidas

A detecção é visual e foi pensada para tabuleiros convencionais 8×8 com
resolução legível. Diagramas muito degradados ou tabelas gráficas que imitam
fortemente uma grade 8×8 ainda podem produzir falsos positivos.

---

Desenvolvido e publicado por **E-Lopes**.
