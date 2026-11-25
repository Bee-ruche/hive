# The local bee's launcher for an assistant whose shell is PowerShell: runs tools/hive/local.sh, beside this file,
# with the bash that Git for Windows installs beside its git, and the same arguments. The launcher is the bash one:
# two copies of the checks that decide a push would drift.
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
& $bash (Join-Path $PSScriptRoot 'local.sh') @args
exit $LASTEXITCODE
