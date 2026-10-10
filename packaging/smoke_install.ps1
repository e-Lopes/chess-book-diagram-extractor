param([Parameter(Mandatory=$true)][string]$Installer, [Parameter(Mandatory=$true)][string]$Version)
$ErrorActionPreference = 'Stop'
$SmokeRoot = Join-Path (Get-Location) 'build\installer-smoke'
$InstallRoot = Join-Path $SmokeRoot 'installed'
New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
$SetupPath = (Resolve-Path -LiteralPath $Installer).Path
# Instala e repete sobre o mesmo diretório: confere o caminho de upgrade sem
# abrir a interface nem executar uma versão baixada de outra release.
foreach ($Pass in 1..2) {
    $Setup = Start-Process -FilePath $SetupPath -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NORESTARTAPPLICATIONS', ('/DIR="' + $InstallRoot + '"'), ('/LOG="' + $SmokeRoot + '\setup-' + $Pass + '.log"')) -WindowStyle Hidden -Wait -PassThru
    if ($Setup.ExitCode -ne 0) { throw "Instalação $Pass falhou: $($Setup.ExitCode)" }
    $ReportPath = Join-Path $SmokeRoot "selftest-$Pass.json"
    $App = Start-Process -FilePath (Join-Path $InstallRoot 'ChessBookDiagramExtractor.exe') -ArgumentList @('--self-test', '--report', ('"' + $ReportPath + '"')) -WindowStyle Hidden -Wait -PassThru
    if ($App.ExitCode -ne 0) { throw "Aplicativo instalado falhou: $($App.ExitCode)" }
    $Report = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
    if (-not $Report.ok -or $Report.versao -ne $Version -or -not $Report.empacotado) { throw 'Diagnóstico ou versão incoerente.' }
}
$Uninstall = Start-Process -FilePath (Join-Path $InstallRoot 'unins000.exe') -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -WindowStyle Hidden -Wait -PassThru
if ($Uninstall.ExitCode -ne 0) { throw "Desinstalação falhou: $($Uninstall.ExitCode)" }
if (Test-Path -LiteralPath (Join-Path $InstallRoot 'ChessBookDiagramExtractor.exe')) { throw 'O aplicativo permaneceu depois da desinstalação.' }
