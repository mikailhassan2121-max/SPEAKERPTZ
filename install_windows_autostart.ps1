[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = "SPEAKERPTZ",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        if ($PSCmdlet.ShouldProcess($TaskName, "Remove current-user startup task")) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        }
    }
    else {
        Write-Host "Task '$TaskName' is not installed."
    }
    exit 0
}

$projectRoot = $PSScriptRoot
$launcher = Join-Path $projectRoot "start_speakerptz.bat"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$config = Join-Path $projectRoot "config\local.yaml"

foreach ($requiredPath in @($launcher, $python, $config)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file is missing: $requiredPath. Run setup_school_windows.bat first."
    }
}

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$launcherArguments = '/d /s /c ""{0}""' -f $launcher
$action = New-ScheduledTaskAction `
    -Execute $env:ComSpec `
    -Argument $launcherArguments `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 7)
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited

if ($PSCmdlet.ShouldProcess($TaskName, "Install current-user startup task")) {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description "Start SPEAKERPTZ after this operator signs in" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    Write-Host "Installed '$TaskName' for $currentUser."
    Write-Host "It runs only after this user signs in and does not enable real PTZ control."
    Write-Host "Test manually first: .\start_speakerptz.bat"
}
