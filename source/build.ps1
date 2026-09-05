param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppName = "YT" + [char]0x4E0B + [char]0x8F7D + [char]0x52A9 + [char]0x624B
$AppVersion = "1.0.1"
$VenvPath = Join-Path $ProjectRoot ".venv-build"
$PythonPath = Join-Path $VenvPath "Scripts\python.exe"
$DistPath = Join-Path $ProjectRoot ("release\" + $AppVersion)
$WorkPath = Join-Path $ProjectRoot "build-cache"
$SpecPath = Join-Path $ProjectRoot "build-spec"
$TclTkStage = Join-Path $WorkPath "tcltk-data"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $VenvPath
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $VenvPath
    }
    else {
        throw "Python 3.10 or newer was not found."
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the build environment (exit code $LASTEXITCODE)."
    }
}

& $PythonPath -c "import struct, sys; raise SystemExit(0 if sys.version_info >= (3, 10) and struct.calcsize('P') == 8 else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "64-bit Python 3.10 or newer is required."
}

if (-not $SkipInstall) {
    & $PythonPath -m pip install -r (Join-Path $ProjectRoot "requirements-build.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to install PyInstaller (exit code $LASTEXITCODE)."
    }
}

& $PythonPath -m unittest discover -s (Join-Path $ProjectRoot "tests") -v
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed (exit code $LASTEXITCODE)."
}

$ResolvedProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$ResolvedTclTkStage = [System.IO.Path]::GetFullPath($TclTkStage)
if (-not $ResolvedTclTkStage.StartsWith($ResolvedProjectRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to prepare Tcl/Tk data outside the project directory."
}

& $PythonPath (Join-Path $ProjectRoot "tools\prepare_tcltk.py") --output $TclTkStage
if ($LASTEXITCODE -ne 0) {
    throw "Unable to prepare Tcl/Tk data (exit code $LASTEXITCODE)."
}

$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", $AppName,
    "--icon", (Join-Path $ProjectRoot "assets\app.ico"),
    "--version-file", (Join-Path $ProjectRoot "version_info.txt"),
    "--paths", (Join-Path $ProjectRoot "src"),
    "--distpath", $DistPath,
    "--workpath", $WorkPath,
    "--specpath", $SpecPath
)

$TclDataPath = Join-Path $TclTkStage "_tcl_data"
$TkDataPath = Join-Path $TclTkStage "_tk_data"
if ((Test-Path -LiteralPath (Join-Path $TclDataPath "init.tcl")) -and
    (Test-Path -LiteralPath (Join-Path $TkDataPath "tk.tcl"))) {
    $PyInstallerArgs += @(
        "--add-data", ($TclDataPath + ";_tcl_data"),
        "--add-data", ($TkDataPath + ";_tk_data")
    )
}
$PyInstallerArgs += (Join-Path $ProjectRoot "src\app.py")

& $PythonPath @PyInstallerArgs

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed (exit code $LASTEXITCODE)."
}

$TargetExe = Join-Path $DistPath ($AppName + ".exe")
if (-not (Test-Path -LiteralPath $TargetExe)) {
    throw "The expected executable was not created."
}

$SmokeResult = Join-Path ([System.IO.Path]::GetTempPath()) ("ytdlp-gui-smoke-" + [Guid]::NewGuid().ToString("N") + ".txt")
$PreviousSmokeResult = $env:YTDLP_GUI_SMOKE_RESULT
$ExistingTargetPids = @(
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $TargetExe } |
        Select-Object -ExpandProperty Id
)
$SmokeSucceeded = $false
$SmokeDeadline = (Get-Date).AddSeconds(20)

try {
    $env:YTDLP_GUI_SMOKE_RESULT = $SmokeResult
    $SmokeProcess = Start-Process -FilePath $TargetExe -ArgumentList "--smoke-test" -PassThru -WindowStyle Hidden

    do {
        Start-Sleep -Milliseconds 100
        $NewTargetProcesses = @(
            Get-Process -ErrorAction SilentlyContinue |
                Where-Object { $_.Path -eq $TargetExe -and $ExistingTargetPids -notcontains $_.Id }
        )
        $SmokeMarkerReady = (Test-Path -LiteralPath $SmokeResult) -and
            ((Get-Content -LiteralPath $SmokeResult -Raw -ErrorAction SilentlyContinue) -eq "ok")
        if ($SmokeMarkerReady -and $NewTargetProcesses.Count -eq 0) {
            $SmokeSucceeded = $true
            break
        }
    } while ((Get-Date) -lt $SmokeDeadline)
}
finally {
    if ($null -eq $PreviousSmokeResult) {
        Remove-Item Env:YTDLP_GUI_SMOKE_RESULT -ErrorAction SilentlyContinue
    }
    else {
        $env:YTDLP_GUI_SMOKE_RESULT = $PreviousSmokeResult
    }

    if (-not $SmokeSucceeded) {
        $ProcessesToStop = @(
            Get-Process -ErrorAction SilentlyContinue |
                Where-Object { $_.Path -eq $TargetExe -and $ExistingTargetPids -notcontains $_.Id }
        )
        if ($ProcessesToStop.Count -gt 0) {
            $ProcessesToStop | Stop-Process -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $SmokeResult -Force -ErrorAction SilentlyContinue
}

if (-not $SmokeSucceeded) {
    throw "Executable smoke test failed: the GUI did not initialize and exit within 20 seconds."
}

$FileHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $TargetExe).Hash
$ChecksumPath = Join-Path $DistPath "SHA256SUMS.txt"
$ChecksumText = $FileHash + "  " + $AppName + ".exe" + [Environment]::NewLine
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($ChecksumPath, $ChecksumText, $Utf8NoBom)

Write-Host "Build complete: $TargetExe"
Write-Host "SHA-256: $FileHash"
