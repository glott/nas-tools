<#
.SYNOPSIS
    Install, validate or uninstall the Task Scheduler task that starts
    crc_shift_bookmarks.pyw whenever CRC launches.

.DESCRIPTION
    Double-click setup_task.cmd to run this. It shows a menu:

        Not installed:   1) Install
        Installed:       2) Validate   3) Uninstall

    Install opens a file dialog to pick crc_shift_bookmarks.pyw (only that
    file can be chosen) and registers the task. The task runs as you, not
    elevated, and only while you're logged on.

    Trigger: when CRC starts it reads its saved login from Windows Credential
    Manager ("Consolidated Radar Client"), and Windows logs that read as
    Security event 5379. Windows logs that event by default, so no system
    settings need changing.

    Windows only lets admins create a task that watches the Security log, so
    Install asks for admin rights (UAC) once. Admin rights are only requested
    when Windows refuses without them.

    Non-interactive use:
        setup_task.ps1 -Action Install -ScriptPath "D:\Tools\crc_shift_bookmarks.pyw"
        setup_task.ps1 -Action Validate
        setup_task.ps1 -Action Uninstall
        setup_task.ps1 -Action Install -ScriptPath ... -DryRun   (check only, change nothing)
#>
[CmdletBinding()]
param(
    [ValidateSet('Menu', 'Install', 'Validate', 'Uninstall')]
    [string]$Action = 'Menu',
    [string]$ScriptPath,
    [string]$PythonwPath,
    [string]$TaskName = 'CRC Shift Bookmarks',
    [switch]$DryRun,
    # Internal / testing:
    [string]$ForUser,
    [switch]$Elevated,
    [switch]$NoElevate
)

$ErrorActionPreference = 'Stop'
$HelperName = 'crc_shift_bookmarks.pyw'
$TaskDescription = 'Shift+Numpad bookmark recall for CRC; starts when CRC launches.'
$TriggerEventId = 5379                               # Credential Manager credentials were read
$CredentialTarget = 'Consolidated Radar Client'      # CRC's saved login
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Wait-Close {
    if ($Elevated) { Read-Host 'Press Enter to close' | Out-Null }
}

function Write-Check([string]$Name, [bool]$Ok, [string]$Detail) {
    if ($Ok) { Write-Host ('  [ OK ] ' + $Name) -ForegroundColor Green -NoNewline }
    else     { Write-Host ('  [FAIL] ' + $Name) -ForegroundColor Red -NoNewline }
    if ($Detail) { Write-Host " - $Detail" } else { Write-Host '' }
    return $Ok
}

function Get-InstalledTask {
    Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

function Get-EventSubscription {
    $select = "*[System[(EventID=$TriggerEventId)]] and *[EventData[Data[@Name='TargetName']='$CredentialTarget']]"
    return "<QueryList><Query Id=`"0`" Path=`"Security`"><Select Path=`"Security`">$select</Select></Query></QueryList>"
}

function Test-IsCrcTrigger([string]$Subscription) {
    return [bool]($Subscription -and $Subscription.Contains("EventID=$TriggerEventId") -and
        $Subscription.Contains("'$CredentialTarget'"))
}

function Test-AccessDenied($ErrorRecord) {
    $e = $ErrorRecord.Exception
    return ($e -is [UnauthorizedAccessException]) -or
        ("$($e.Message)" -match 'Access is denied|0x80070005|E_ACCESSDENIED')
}

function Resolve-FullPath([string]$Path, [string]$What, [string]$Hint) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$What not found: $Path  ($Hint)"
    }
    return (Get-Item -LiteralPath $Path).FullName
}

function Find-Pythonw {
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Invoke-Elevated([string]$ElevatedAction, [string[]]$ExtraArgs) {
    # Re-run this script as admin for one action and wait for it to finish.
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA',
        '-File', "`"$PSCommandPath`"", '-Action', $ElevatedAction,
        '-TaskName', "`"$TaskName`"", '-ForUser', "`"$ForUser`"", '-Elevated') + $ExtraArgs
    Write-Host 'Windows only lets admins create or remove tasks that watch the Security'
    Write-Host 'event log (where the "CRC started" event is). Asking for admin rights...'
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList $argList
}

function Select-HelperScript {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Select $HelperName"
    $dialog.Filter = "CRC Shift Bookmarks helper ($HelperName)|$HelperName"
    $dialog.FileName = $HelperName
    $dialog.CheckFileExists = $true
    $dialog.Multiselect = $false
    if (Test-Path -LiteralPath (Join-Path $ScriptDir $HelperName)) {
        $dialog.InitialDirectory = $ScriptDir
    }
    # A hidden top-most owner keeps the dialog from opening behind the console.
    $owner = New-Object System.Windows.Forms.Form
    $owner.TopMost = $true
    try {
        while ($true) {
            if ($dialog.ShowDialog($owner) -ne [System.Windows.Forms.DialogResult]::OK) {
                return $null
            }
            if ((Split-Path -Leaf $dialog.FileName) -eq $HelperName) {
                return $dialog.FileName
            }
            Write-Host "  Please select $HelperName (you picked $(Split-Path -Leaf $dialog.FileName))." -ForegroundColor Yellow
            $dialog.InitialDirectory = Split-Path -Parent $dialog.FileName
            $dialog.FileName = $HelperName
        }
    } finally {
        $owner.Dispose()
        $dialog.Dispose()
    }
}

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

function Install-Task {
    if (Get-InstalledTask) {
        Write-Host "The task '$TaskName' is already installed. Uninstall it first to reinstall." -ForegroundColor Yellow
        return
    }

    $script = $ScriptPath
    if (-not $script) {
        Write-Host "Select $HelperName in the file dialog..."
        $script = Select-HelperScript
        if (-not $script) { Write-Host 'Cancelled.'; return }
    }
    $script = Resolve-FullPath $script 'Helper script' 'use -ScriptPath to point at it'
    if ((Split-Path -Leaf $script) -ne $HelperName) { throw "The helper script must be named $HelperName" }
    $py = $PythonwPath
    if (-not $py) { $py = Find-Pythonw }
    $py = Resolve-FullPath $py 'pythonw.exe' 'install Python, or use -PythonwPath'
    if ($py -like '*\WindowsApps\*') {
        Write-Warning "pythonw.exe is a Microsoft Store alias ($py); Task Scheduler may not be able to start it."
    }

    $subscription = Get-EventSubscription
    Write-Host ''
    Write-Host "  Task name : $TaskName"
    Write-Host "  Runs as   : $ForUser (not elevated, only while logged on)"
    Write-Host "  Trigger   : CRC starts (reads its saved login, Security event $TriggerEventId)"
    Write-Host "  Action    : `"$py`" `"$script`""
    Write-Host ''

    if ($DryRun) {
        [xml]$subscription | Out-Null
        # Run the same query against a log anyone can read, to check its syntax.
        $probe = $subscription.Replace('Path="Security"', 'Path="Application"')
        try { Get-WinEvent -FilterXml ([xml]$probe) -MaxEvents 1 -ErrorAction Stop | Out-Null }
        catch {
            if ($_.Exception.Message -notmatch 'No events were found') {
                throw "Event query is invalid: $($_.Exception.Message)"
            }
        }
        $class = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
        $null = New-CimInstance -CimClass $class -ClientOnly
        Write-Host "  Subscription: $subscription"
        Write-Host '[dry run] OK - nothing was changed.' -ForegroundColor Green
        return
    }

    $class = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
    $trigger = New-CimInstance -CimClass $class -ClientOnly
    $trigger.Enabled = $true
    $trigger.Subscription = $subscription

    $action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" `
        -WorkingDirectory (Split-Path -Parent $script)
    $principal = New-ScheduledTaskPrincipal -UserId $ForUser -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

    try {
        Register-ScheduledTask -TaskName $TaskName -Trigger $trigger -Action $action `
            -Principal $principal -Settings $settings -Description $TaskDescription | Out-Null
    } catch {
        if ((Test-AccessDenied $_) -and -not (Test-Admin) -and -not $NoElevate) {
            Invoke-Elevated 'Install' @('-ScriptPath', "`"$script`"", '-PythonwPath', "`"$py`"")
            return
        }
        throw
    }

    Write-Host "Installed task '$TaskName'. It will start the next time CRC launches." -ForegroundColor Green
    Write-Host ''
    Test-Task | Out-Null
}

function Test-Task {
    $task = Get-InstalledTask
    Write-Host "Validating '$TaskName':"
    if (-not (Write-Check 'Task is installed' ([bool]$task) '')) { return $false }

    $ok = $true
    $ok = (Write-Check 'Task is enabled' ($task.State -ne 'Disabled') "state: $($task.State)") -and $ok

    $act = @($task.Actions)[0]
    $py = $act.Execute
    $ok = (Write-Check 'Python found' ([bool]$py -and (Test-Path -LiteralPath $py)) $py) -and $ok

    $script = ''
    if ($act.Arguments) { $script = $act.Arguments.Trim().Trim('"') }
    $scriptOk = $script -and (Test-Path -LiteralPath $script) -and ((Split-Path -Leaf $script) -eq $HelperName)
    $detail = $script
    if (-not $scriptOk) { $detail = "$script  (moved? uninstall and install again)" }
    $ok = (Write-Check "$HelperName found" ([bool]$scriptOk) $detail) -and $ok

    $trig = @($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskEventTrigger' })[0]
    $trigOk = $trig -and $trig.Enabled -and (Test-IsCrcTrigger $trig.Subscription)
    $ok = (Write-Check 'Triggers on CRC launch' ([bool]$trigOk) "Security event $TriggerEventId, '$CredentialTarget'") -and $ok

    $p = $task.Principal
    $ok = (Write-Check 'Runs as you, not elevated' ($p.RunLevel -eq 'Limited') "$($p.UserId), $($p.RunLevel)") -and $ok

    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($info) {
        $last = 'never (it runs the next time CRC launches)'
        if ($info.LastRunTime -and $info.LastRunTime.Year -gt 2000) {
            $last = "$($info.LastRunTime) (result 0x{0:X})" -f $info.LastTaskResult
        }
        Write-Host "  Last run: $last"
    }

    Write-Host ''
    if ($ok) { Write-Host 'All checks passed.' -ForegroundColor Green }
    else     { Write-Host 'Some checks failed.' -ForegroundColor Red }
    return $ok
}

function Remove-Task {
    if (-not (Get-InstalledTask)) { Write-Host "No task named '$TaskName' is installed."; return }
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    } catch {
        if ((Test-AccessDenied $_) -and -not (Test-Admin) -and -not $NoElevate) {
            Invoke-Elevated 'Uninstall' @()
            return
        }
        throw
    }
    Write-Host "Removed task '$TaskName'." -ForegroundColor Green
}

function Show-Menu {
    while ($true) {
        $installed = [bool](Get-InstalledTask)
        Write-Host ''
        Write-Host '=== CRC Shift Bookmarks - scheduled task setup ===' -ForegroundColor Cyan
        if ($installed) { Write-Host "Status: installed ('$TaskName')" }
        else            { Write-Host 'Status: not installed' }
        Write-Host ''
        if ($installed) {
            Write-Host '  2) Validate'
            Write-Host '  3) Uninstall'
        } else {
            Write-Host '  1) Install'
        }
        Write-Host '  Q) Quit'
        $choice = (Read-Host 'Choose').Trim().ToUpper()
        Write-Host ''
        try {
            switch ($choice) {
                '1' { if ($installed) { Write-Host 'Already installed.' } else { Install-Task } }
                '2' { if ($installed) { Test-Task | Out-Null } else { Write-Host 'Not installed yet.' } }
                '3' { if ($installed) { Remove-Task } else { Write-Host 'Not installed yet.' } }
                'Q' { return }
                default { Write-Host "Unknown choice '$choice'." -ForegroundColor Yellow }
            }
        } catch {
            Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

try {
    if (-not $ForUser) { $ForUser = "$env:USERDOMAIN\$env:USERNAME" }
    if (-not $PythonwPath) { $PythonwPath = Find-Pythonw }

    switch ($Action) {
        'Menu'      { Show-Menu }
        'Install'   { Install-Task }
        'Validate'  { if (-not (Test-Task)) { Wait-Close; exit 1 } }
        'Uninstall' { Remove-Task }
    }
    if ($Action -ne 'Menu') { Wait-Close }
    exit 0
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Wait-Close
    exit 1
}
