# Distribuição para Windows

## Resultado para o usuário

O instalador contém o interpretador Python, bibliotecas nativas, interface,
modelo ONNX, ícones e licenças. Por isso o computador de destino não precisa ter
Python, OpenCV, PyMuPDF ou ONNX Runtime instalados. A versão atual é destinada a
Windows 10 e 11 de 64 bits.

O Inno Setup instala por usuário em
`%LOCALAPPDATA%\Programs\Chess Book Diagram Extractor`, sem exigir privilégios
de administrador. Ele registra **E-Lopes** como editor, cria entradas no menu
Iniciar, oferece um atalho opcional na área de trabalho e instala o desinstalador
normal do Windows.

## Dependências

Dependências de execução, fixadas por faixas em `requirements.txt`:

| Pacote | Uso |
|---|---|
| PyMuPDF | leitura, renderização e criação de PDFs |
| OpenCV | contornos, perspectiva, filtros e descritores HOG |
| NumPy | matrizes, estatística e preparação das imagens |
| ttkbootstrap | tema e widgets da interface |
| ONNX Runtime | inferência local das peças |

`requirements-build.txt` acrescenta PyInstaller e Pillow. O modelo e sua
licença são ativos do aplicativo, não dependências baixadas em execução.

## Build local

Em um Windows com Python 3.12 e Inno Setup 6:

```powershell
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
.\build_windows.ps1 -Version 0.2.0
```

O script prepara o ícone, gera metadados de versão, executa o PyInstaller e
compila `packaging/installer.iss`. O resultado versionado fica em:

`release\ChessBookDiagramExtractor-Setup-v<versão>.exe`

O parâmetro `-SkipInstaller` pode ser usado para gerar apenas a pasta do
aplicativo durante testes de empacotamento.

## PyInstaller

`DiagramExtractor.spec` usa `interface_windows.py` como entrada e cria um
aplicativo `windowed`, sem console. Ele inclui explicitamente:

- dados e binários do OpenCV e ttkbootstrap;
- ONNX Runtime;
- ícones PNG e ICO;
- `models/chess-tiles-v2.onnx`;
- licença MIT do fenshot e avisos de terceiros;
- metadados de versão gerados no build.

O build é do tipo `onedir`, coletado em `dist/ChessBookDiagramExtractor`. Essa
opção simplifica o carregamento das DLLs e reduz o tempo de abertura em relação
a extrair um executável `onefile` a cada execução. O instalador continua sendo
um único arquivo para download.

## Instalador e desinstalação

`packaging/installer.iss` usa um `AppId` estável. Esse identificador permite que
uma versão nova substitua a anterior em vez de criar várias instalações. O
instalador também remove atalhos e nomes legados conhecidos durante o upgrade.

A desinstalação pode ser iniciada pelo menu Iniciar ou por **Configurações >
Aplicativos > Aplicativos instalados**. O executável `unins000.exe` é criado
pelo Inno Setup na pasta do programa.

## Integração contínua e releases

`.github/workflows/windows-release.yml` executa em `windows-latest` quando há:

- push para `main`;
- tag no formato `v*`;
- execução manual com uma versão informada.

O job instala Python 3.12, executa todos os testes, gera o aplicativo e compila
o instalador. Builds comuns ficam disponíveis como artefatos da ação. Uma
GitHub Release só é criada para tags.

Fluxo recomendado para publicar:

1. atualizar `version.py` e os valores padrão de build quando necessário;
2. executar os testes localmente;
3. fazer commit e push em `main`;
4. criar e enviar a tag, por exemplo `v0.2.1`;
5. conferir o job e testar o instalador da Release em uma máquina limpa.

Além do arquivo versionado, a automação cria
`ChessBookDiagramExtractor-Setup.exe`. Esse nome permanente alimenta o botão de
download do README, que sempre aponta para a última Release.

## Atualizador

Ao iniciar ou por solicitação no menu **Opções**, a aplicação consulta
`/releases/latest` na API do GitHub. A atualização é oferecida somente se a tag
contiver uma versão semântica maior que a instalada.

Antes de executar o instalador, o atualizador verifica:

- nome exato `ChessBookDiagramExtractor-Setup-v<versão>.exe`;
- URL pertencente à Release do repositório configurado;
- tamanho informado, positivo e limitado a 350 MiB;
- tamanho efetivamente recebido;
- digest SHA-256 publicado pelo GitHub.

O download é feito como `.partial` em uma pasta temporária. Somente após todas
as verificações ele substitui o destino e inicia o Setup com `/SILENT`,
`/CLOSEAPPLICATIONS` e `/NORESTART`.

## Assinatura e SmartScreen

O projeto possui `CODE_SIGNING_POLICY.md` e `PRIVACY.md` para a integração com o
SignPath. Enquanto um instalador não estiver efetivamente assinado por um
certificado confiável, o Windows SmartScreen pode exibir “Windows protegeu o
computador”. Publicar o arquivo no GitHub e validar seu SHA-256 protege a
integridade do download, mas não substitui uma assinatura Authenticode.

Uma release só deve ser anunciada como assinada depois de confirmar a assinatura
nas propriedades do arquivo e no pipeline correspondente.

## Checklist de publicação

- Todos os testes automatizados passaram.
- O modelo incluído corresponde ao SHA-256 esperado.
- Versão da aplicação, metadados e tag são coerentes.
- Ícones corretos aparecem na janela, executável, Setup e atalhos novos.
- Instalação, atualização e desinstalação foram testadas.
- O EXE foi executado em Windows 64 bits sem Python instalado.
- Um PDF com zero, um e vários diagramas foi validado.
- A Release contém o instalador versionado e o link permanente.

