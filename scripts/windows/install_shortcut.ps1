# Crea (o actualiza) el acceso directo "JobBot" en el escritorio: abre el panel de vacantes.
# Uso:   powershell -ExecutionPolicy Bypass -File scripts\windows\install_shortcut.ps1
# Quitar: borrar "JobBot" del escritorio.
# Si tus datos no están en ~\JobBot, define la variable de usuario JOBBOT_HOME (Configuración >
# Sistema > Información > Configuración avanzada > Variables de entorno): el acceso la usa.
param([string]$Name = 'JobBot')

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$exe = Join-Path $root '.venv\Scripts\jobbot-panel.exe'

# jobbot-panel.exe lo crea `uv sync` (pyproject: [project.gui-scripts]); corre sin ventana de consola.
if (-not (Test-Path $exe)) {
    Push-Location $root
    uv sync
    Pop-Location
}
if (-not (Test-Path $exe)) { throw "No se encontró $exe; corre 'uv sync' en $root." }

$desktop = [Environment]::GetFolderPath('Desktop')   # respeta el escritorio movido a OneDrive
$link = Join-Path $desktop "$Name.lnk"
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = Join-Path $root 'src\jobbot\panel\jobbot.ico'
$shortcut.Description = 'Panel de vacantes de JobBot'
$shortcut.Save()

"Acceso directo listo: $link"
