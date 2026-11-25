# The local bee's launcher for an assistant whose shell is PowerShell: runs tools/hive/local.sh, beside this file,
# with the bash that Git for Windows installs beside its git, and the same arguments. The launcher is the bash one:
# two copies of the checks that decide a push would drift.
#
# Windows PowerShell 5.1 drops an empty argument and breaks one that holds a double quote when it starts a program
# itself: the command line is built here, every argument quoted as the bash of Git for Windows reads it back, and
# quoted always, so that no « * » is ever expanded on the way.
$ErrorActionPreference = 'Stop'
$git = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $git) {
    [Console]::Error.WriteLine('hive: git is not on this machine''s PATH: install Git for Windows')
    exit 2
}
$bash = Join-Path (Split-Path (Split-Path $git.Source -Parent) -Parent) 'bin\bash.exe'
if (-not (Test-Path -LiteralPath $bash -PathType Leaf)) {
    [Console]::Error.WriteLine('hive: no bash.exe beside this git (Git for Windows installs one): install Git for Windows')
    exit 2
}

function ConvertTo-QuotedArgument([string] $text) {
    # (Inside double quotes, the bash of Git for Windows reads « \\ » as one backslash and « \" » as a quote.)
    return '"' + $text.Replace('\', '\\').Replace('"', '\"') + '"'
}

$words = @((Join-Path $PSScriptRoot 'local.sh')) + @($args | ForEach-Object { [string] $_ })
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $bash
$start.Arguments = (($words | ForEach-Object { ConvertTo-QuotedArgument $_ }) -join ' ')
$start.UseShellExecute = $false
$process = [System.Diagnostics.Process]::Start($start)
$process.WaitForExit()
exit $process.ExitCode
