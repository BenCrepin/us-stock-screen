# Registers (or re-registers) the Windows Task Scheduler job that runs the screen
# every day at 10:00 local time. The machine is on "GMT Standard Time" (UK), so this
# tracks BST/GMT automatically. Run from the project folder:
#     powershell -ExecutionPolicy Bypass -File .\setup_schedule.ps1
# Remove with:
#     Unregister-ScheduledTask -TaskName "US Stock Screen Daily" -Confirm:$false

$TaskName = "US Stock Screen Daily"
$Here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python   = (Get-Command python.exe | Where-Object { $_.Source -notlike "*WindowsApps*" } | Select-Object -First 1).Source
if (-not $Python) { $Python = (Get-Command python.exe).Source }

$Action  = New-ScheduledTaskAction -Execute $Python -Argument "`"$Here\run_daily.py`"" -WorkingDirectory $Here
$Trigger = New-ScheduledTaskTrigger -Daily -At 10:00
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
            -WakeToRun -MultipleInstances IgnoreNew -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Runs run_daily.py: refreshes S&P 500/400 universe, screens for profit growth + SMA200 proximity, writes dated archive. 10:00 UK time daily." | Out-Null

$t = Get-ScheduledTask -TaskName $TaskName
$info = $t | Get-ScheduledTaskInfo
Write-Output "Registered '$TaskName'"
Write-Output "  Python : $Python"
Write-Output "  Script : $Here\run_daily.py"
Write-Output "  Next run: $($info.NextRunTime)"
