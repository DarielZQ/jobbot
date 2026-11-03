# Registra (o actualiza) la búsqueda diaria de JobBot en el Programador de tareas de Windows.
# Uso:   powershell -ExecutionPolicy Bypass -File scripts\windows\install_schedule.ps1 [-At 07:00]
#        [-JobbotHome C:\ruta\a\tus\datos]   (si no usas ~\JobBot ni la variable JOBBOT_HOME)
# Quitar: Unregister-ScheduledTask -TaskName 'JobBot - busqueda diaria' -Confirm:$false
param([string]$At = '07:00', [string]$JobbotHome = '')

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runner = Join-Path $root 'scripts\windows\run_daily.ps1'
$taskName = 'JobBot - busqueda diaria'

$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`""
if ($JobbotHome) { $arguments += " -JobbotHome `"$JobbotHome`"" }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $At
# StartWhenAvailable: si la computadora estaba apagada a esa hora, corre apenas se encienda.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Busca vacantes con JobBot, genera el informe diario y avisa si hay nuevas.' `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
"Tarea: $($task.TaskName) | Estado: $($task.State) | Próxima corrida: $($info.NextRunTime)"
