param(
    [string]$Version = "0.4.1",
    [string]$Repository = "e-Lopes/chess-book-diagram-extractor",
    [string]$Publisher = "E-Lopes",
    [switch]$SkipInstaller,
    [switch]$SkipDependencies
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot
$BuildPython = Join-Path $ProjectRoot ".build-venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $BuildPython)) {
    Write-Host "Criando ambiente isolado de build..."
    python -m venv .build-venv
}

Write-Host "Instalando/atualizando dependencias de build..."
if (-not $SkipDependencies) {
& $BuildPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) {
    throw "A instalacao das dependencias terminou com o codigo $LASTEXITCODE."
}
}

Write-Host "Executando testes..."
& $BuildPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    throw "Os testes terminaram com o codigo $LASTEXITCODE."
}

Write-Host "Gerando aplicativo Windows..."
& $BuildPython packaging\prepare_icon.py
if ($LASTEXITCODE -ne 0) {
    throw "A preparacao do icone terminou com o codigo $LASTEXITCODE."
}
$MetadataArgs = @(
    "packaging\generate_build_metadata.py",
    "--version", $Version,
    "--publisher", $Publisher
)
if ($Repository) {
    $MetadataArgs += @("--repository", $Repository)
}
& $BuildPython @MetadataArgs
if ($LASTEXITCODE -ne 0) {
    throw "A geracao dos metadados terminou com o codigo $LASTEXITCODE."
}
& $BuildPython -m PyInstaller --clean --noconfirm DiagramExtractor.spec
if ($LASTEXITCODE -ne 0) {
    throw "O PyInstaller terminou com o codigo $LASTEXITCODE."
}
$SelfTestReport = Join-Path $ProjectRoot 'build\selftest-packaged.json'
$SelfTest = Start-Process -FilePath (Join-Path $ProjectRoot 'dist\ChessBookDiagramExtractor\ChessBookDiagramExtractor.exe') -ArgumentList @('--self-test', '--report', ('"' + $SelfTestReport + '"')) -WindowStyle Hidden -Wait -PassThru
if ($SelfTest.ExitCode -ne 0) { throw "O aplicativo empacotado falhou no diagnóstico. Confira $SelfTestReport" }
$SelfTestData = Get-Content -LiteralPath $SelfTestReport -Raw | ConvertFrom-Json
if (-not $SelfTestData.ok -or $SelfTestData.versao -ne $Version -or $SelfTestData.repositorio -ne $Repository) { throw 'Metadados do aplicativo incoerentes.' }

if ($SkipInstaller) {
    Write-Host "Aplicativo gerado em dist\ChessBookDiagramExtractor"
    exit 0
}

$CompilerCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$Iscc = $CompilerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 nao encontrado. Instale-o ou use -SkipInstaller para gerar apenas o aplicativo."
}

Write-Host "Gerando instalador..."
$ProjectURL = if ($Repository) { "https://github.com/$Repository" } else { "" }
& $Iscc "/DMyAppVersion=$Version" "/DMyAppPublisher=$Publisher" "/DMyAppURL=$ProjectURL" "packaging\installer.iss"
if ($LASTEXITCODE -ne 0) {
    throw "O Inno Setup terminou com o codigo $LASTEXITCODE."
}
Copy-Item -LiteralPath "release\ChessBookDiagramExtractor-Setup-v$Version.exe" -Destination 'release\ChessBookDiagramExtractor-Setup.exe'
& $BuildPython packaging\prepare_release.py --version $Version
if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar inventário SHA-256.' }
Write-Host "Instalador concluido em release\ChessBookDiagramExtractor-Setup-v$Version.exe"
