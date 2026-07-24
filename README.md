<p align="center">
  <img src="icon/icon.png" alt="Ícone do Chess Book Diagram Extractor" width="170">
</p>

<h1 align="center">Chess Book Diagram Extractor</h1>

<p align="center">
  Extraia automaticamente diagramas 8×8 de livros de xadrez em PDF.
</p>

<p align="center">
  <a href="https://github.com/e-Lopes/chess-book-diagram-extractor/releases/latest/download/ChessBookDiagramExtractor-Setup.exe">
    <img src="https://img.shields.io/badge/Baixar_para_Windows-176B5B?style=for-the-badge&logo=windows11&logoColor=white" alt="Baixar para Windows">
  </a>
</p>

O **Chess Book Diagram Extractor** é um aplicativo gratuito para Windows que
localiza automaticamente diagramas de tabuleiros em livros de xadrez. Ele gera
um novo PDF A4 com um diagrama centralizado por página, pronto para imprimir,
organizar ou estudar.

## Principais recursos

- Detecta páginas com zero, um ou vários diagramas.
- Recorta as 64 casas, as peças e a borda imediata do tabuleiro.
- Corrige pequenas inclinações e elimina detecções duplicadas.
- Filtra ilustrações, peças isoladas e outros falsos positivos comuns.
- Preserva a ordem em que os diagramas aparecem no livro.
- Cria um PDF A4 branco com um diagrama centralizado por página.
- Verifica novas versões e valida o SHA-256 antes de atualizar.
- Inclui desinstalador e não exige Python ou bibliotecas adicionais.

## Baixar e instalar

1. Clique no botão **Baixar para Windows** no início desta página.
2. Execute `ChessBookDiagramExtractor-Setup.exe`.
3. Siga as instruções do instalador.
4. Abra **Chess Book Diagram Extractor** pelo menu Iniciar.

O aplicativo é compatível com Windows 10 e Windows 11 de 64 bits e é instalado
somente para o usuário atual.

> Enquanto o projeto não possuir um certificado de assinatura de código, o
> Windows SmartScreen poderá mostrar um aviso na primeira execução do
> instalador.

## Como usar

1. Clique em **Selecionar PDF** e escolha o livro.
2. O aplicativo sugere automaticamente um arquivo com o sufixo `_diagramas.pdf`.
3. Se necessário, clique em **Alterar** para escolher outro local de saída.
4. Marque ou desmarque **Abrir o PDF ao concluir**.
5. Clique em **Extrair diagramas**.
6. Ao terminar, use **Abrir PDF** ou **Abrir pasta**.

O livro original nunca é alterado.

## Atualizações automáticas

Ao iniciar, o aplicativo consulta a versão mais recente publicada neste
repositório. Quando houver uma atualização, ele solicita confirmação antes de
baixar e instalar qualquer arquivo. O instalador baixado só é executado após a
validação de seu hash SHA-256.

Também é possível abrir o menu no canto superior direito e escolher
**Verificar atualizações**.

## Como desinstalar

Use uma destas opções do Windows:

- abra **Desinstalar Chess Book Diagram Extractor** no menu Iniciar; ou
- acesse **Configurações > Aplicativos > Aplicativos instalados**.

O Editor exibido pelo Windows é **E-Lopes**.

## Segurança e privacidade

O processamento dos livros acontece localmente no computador. O arquivo PDF
não é enviado para servidores externos. A internet é usada somente para
verificar e baixar atualizações.

Consulte a [Política de Privacidade](PRIVACY.md) e a
[Política de assinatura de código](CODE_SIGNING_POLICY.md).

O projeto solicitou a assinatura gratuita fornecida por
[SignPath.io](https://signpath.io/), com certificado da
[SignPath Foundation](https://signpath.org/). Versões publicadas antes da
conclusão dessa integração podem não possuir assinatura digital.

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

## Limitações conhecidas

A detecção visual foi desenvolvida para tabuleiros convencionais 8×8 com
resolução legível. Diagramas muito degradados ou elementos gráficos que imitam
fortemente uma grade 8×8 ainda podem produzir falsos positivos.

---

<p align="center">
  Desenvolvido e publicado por <strong>E-Lopes</strong> · Licença MIT
</p>
