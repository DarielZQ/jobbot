# Corrida diaria de JobBot. La ejecuta el Programador de tareas de Windows
# (registrado con scripts\windows\install_schedule.ps1). Ver docs/getting-started.md.
# -JobbotHome: tu carpeta de datos; por defecto, la variable JOBBOT_HOME o ~\JobBot.
param([string]$JobbotHome = '')
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
if ($JobbotHome) { $env:JOBBOT_HOME = $JobbotHome }
$home_dir = if ($env:JOBBOT_HOME) { $env:JOBBOT_HOME } else { Join-Path $env:USERPROFILE 'JobBot' }

$logDir = Join-Path $home_dir 'data\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ('daily-{0:yyyy-MM-dd}.log' -f (Get-Date))

# uv puede no estar en el PATH del Programador de tareas: probar las rutas de instalación habituales
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
foreach ($candidate in @(
    (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
    (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
)) {
    if (-not $uv -and (Test-Path $candidate)) { $uv = $candidate }
}

"=== $(Get-Date -Format s) ===" | Out-File -FilePath $log -Append -Encoding utf8
if (-not $uv) {
    'ERROR: no se encontró uv.exe' | Out-File -FilePath $log -Append -Encoding utf8
    exit 1
}
& $uv run jobbot daily 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $log -Append -Encoding utf8
exit $LASTEXITCODE
