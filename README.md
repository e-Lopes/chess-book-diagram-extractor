# Chess Book Diagram Extractor

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

1. Abra a página **Releases** deste repositório.
2. Na versão mais recente, baixe
   `ChessBookDiagramExtractor-Setup-vX.Y.Z.exe`.
3. Execute o arquivo baixado e siga o assistente.
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

## Executar o código-fonte

Requer Python 3.10 ou mais recente. Na raiz do repositório:

```powershell
python -m pip install -r requirements.txt
python interface_windows.py
```

No Windows, depois de instalar as dependências, também é possível dar duplo
clique em `Iniciar_Extrator.bat`.

A versão com seletores nativos e mensagens no terminal pode ser iniciada com:

```powershell
python extrair_tabuleiros_pdf.py
```

## Testes

```powershell
python -m unittest discover -s tests -v
```

Os testes usam PDFs e imagens sintéticos em uma pasta temporária. Eles cobrem
páginas sem diagramas, um ou vários diagramas, inclinação, duplicatas, filtros
de falsos positivos, saída A4, atualização e situações de erro.

## Gerar o EXE e o instalador

O build exige Windows. O script cria `.build-venv`, instala as dependências de
build e gera o aplicativo sem alterar o ambiente Python principal.

Para gerar somente `dist/ChessBookDiagramExtractor`:

```powershell
.\Build_Windows.bat -SkipInstaller
```

Para gerar o instalador, tenha o Inno Setup 6 instalado e execute:

```powershell
.\Build_Windows.bat -Version 0.1.2 -Repository SEU_USUARIO/chess-book-diagram-extractor
```

O resultado será
`release/ChessBookDiagramExtractor-Setup-v0.1.2.exe`. O endereço do
repositório é incorporado ao build para habilitar as atualizações.

## Publicar uma versão

O workflow em `.github/workflows/windows-release.yml` executa os testes e cria
o instalador em um runner Windows. Para publicar uma release:

```powershell
git tag v0.1.2
git push origin v0.1.2
```

A tag `vX.Y.Z` gera automaticamente a GitHub Release e anexa o instalador com
o nome esperado pelo atualizador.

## Limitações conhecidas

A detecção é visual e foi pensada para tabuleiros convencionais 8×8 com
resolução legível. Diagramas muito degradados ou tabelas gráficas que imitam
fortemente uma grade 8×8 ainda podem produzir falsos positivos.

---

Desenvolvido e publicado por **E-Lopes**.
