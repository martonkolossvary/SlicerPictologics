#requires -Version 5.1
<# Launch one owned Slicer, preserving existing sessions and process environment.
Raw output is local evidence and must be privacy-reviewed before publication. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SlicerExe,
    [Parameter(Mandatory)][string]$Script,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [hashtable]$Environment = @{},
    [switch]$Visible
)
$ErrorActionPreference = 'Stop'

function ConvertTo-WindowsArgument([string]$Value) {
    # Windows PowerShell 5.1 has no ProcessStartInfo.ArgumentList. Quote each argument
    # so that the program reads it back unchanged (the CommandLineToArgvW rules).
    if ($Value -and $Value -notmatch '[\s"]') { return $Value }
    $quoted = '"'
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq [char]'\') { $backslashes++; continue }
        if ($character -eq [char]'"') { $quoted += '\' * (2 * $backslashes + 1) }
        else { $quoted += '\' * $backslashes }
        $quoted += $character
        $backslashes = 0
    }
    return $quoted + ('\' * (2 * $backslashes)) + '"'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$executablePath = (Resolve-Path -LiteralPath $SlicerExe).Path
$scriptPath = (Resolve-Path -LiteralPath $Script).Path
# GetFullPath would use the process folder, which Set-Location does not change.
$outputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
if (Test-Path -LiteralPath $outputPath) { throw 'Use a new launch output directory.' }
New-Item -ItemType Directory -Path $outputPath | Out-Null
$startInfo = [Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $executablePath
$startInfo.WorkingDirectory = $repoRoot
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = -not $Visible
$startInfo.WindowStyle = if ($Visible) { 'Normal' } else { 'Hidden' }
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$launchArguments = @('--no-splash', '--disable-settings', '--ignore-slicerrc')
if (-not $Visible) { $launchArguments += '--no-main-window' }
$launchArguments += @('--additional-module-paths', (Join-Path $repoRoot 'PictologicsSlicer'),
    (Join-Path $repoRoot 'PictologicsCLI'), '--python-script', $scriptPath)
$startInfo.Arguments = ($launchArguments | ForEach-Object { ConvertTo-WindowsArgument $_ }) -join ' '
foreach ($key in @('PYTHONPATH', 'PYTHONHOME', 'PICTOLOGICS_DEV_SOURCE')) {
    $startInfo.Environment.Remove($key) | Out-Null
}
if ($Environment.ContainsKey('PICTOLOGICS_DEV_SOURCE')) { throw 'Development source overrides are forbidden for acceptance.' }
foreach ($key in $Environment.Keys) { $startInfo.Environment[$key] = [string]$Environment[$key] }
$process = [Diagnostics.Process]::new()
$process.StartInfo = $startInfo
$stdout = [IO.FileStream]::new((Join-Path $outputPath 'stdout.log'), 'CreateNew', 'Write', 'ReadWrite', 1)
$stderr = [IO.FileStream]::new((Join-Path $outputPath 'stderr.log'), 'CreateNew', 'Write', 'ReadWrite', 1)
$started = [DateTimeOffset]::UtcNow
try {
    if (-not $process.Start()) { throw 'Slicer failed to start.' }
    $outCopy = $process.StandardOutput.BaseStream.CopyToAsync($stdout)
    $errCopy = $process.StandardError.BaseStream.CopyToAsync($stderr)
    $process.WaitForExit()
    $outCopy.GetAwaiter().GetResult() | Out-Null
    $errCopy.GetAwaiter().GetResult() | Out-Null
    $exitCode = $process.ExitCode
    $report = [ordered]@{ started_utc=$started.ToString('o'); finished_utc=[DateTimeOffset]::UtcNow.ToString('o');
        exit_code=$exitCode; launcher_pid=$process.Id; slicer_executable=$executablePath; script=$scriptPath;
        source_revision=(& git -C $repoRoot rev-parse HEAD); arguments=$launchArguments }
    $report | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $outputPath 'process.json')
    Write-Output "Slicer exit code: $exitCode; local evidence: $outputPath"
} finally {
    $stdout.Dispose()
    $stderr.Dispose()
    $process.Dispose()
}
exit $exitCode
