# Zensar Content Studio - one-click setup + launch (Windows 10/11, Windows PowerShell 5.1+).
# Called by start.bat. Safe to run repeatedly: every step is skipped when already done.
#
#   Environment switches (optional):
#     ZCS_SKIP_AI=1        do not offer to install Ollama / a local model
#     ZCS_ASSUME_YES=1     answer "yes" to all prompts (unattended install)
#     ZCS_NO_BROWSER=1     do not open the browser
#     ZCS_PORT=8000        port for the local server

# Native tools (pip/npm/ollama) write progress to stderr; in Windows PowerShell 5.1 that must not
# abort the script, so every step checks $LASTEXITCODE explicitly instead.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$env:PYTHONUTF8 = "1"            # log files and redirected output are always UTF-8
$env:PYTHONIOENCODING = "utf-8"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Port = if ($env:ZCS_PORT) { [int]$env:ZCS_PORT } else { 8000 }
$Url = "http://localhost:$Port"
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null

function Step($n, $text) { Write-Host ""; Write-Host "[$n] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    OK  $text" -ForegroundColor Green }
function Info($text) { Write-Host "    ..  $text" }
function Warn($text) { Write-Host "    !!  $text" -ForegroundColor Yellow }
function Fail($text) {
    Write-Host ""; Write-Host "SETUP FAILED: $text" -ForegroundColor Red
    Write-Host "Details are in $LogDir" -ForegroundColor Red
    exit 1
}
function Ask($question) {
    if ($env:ZCS_ASSUME_YES -eq "1") { return $true }
    $a = Read-Host "$question [Y/n]"
    return ($a -eq "" -or $a -match "^[yY]")
}
function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u"
}
function File-Hash($paths) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $sb = New-Object System.Text.StringBuilder
    foreach ($p in $paths) {
        if (Test-Path $p -PathType Leaf) {
            [void]$sb.Append([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($p))))
        }
    }
    return [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($sb.ToString()))).Replace("-", "")
}
function Run-Logged($exe, [string]$arguments, $log) {
    # Separate stdout/stderr files: stderr never becomes a PowerShell error and arguments pass verbatim
    $out = [IO.Path]::GetTempFileName(); $err = [IO.Path]::GetTempFileName()
    $p = Start-Process -FilePath $exe -ArgumentList $arguments -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle
    $p.WaitForExit()
    Get-Content $out, $err | Add-Content $log
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    return $p.ExitCode
}
function Have-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }
function Winget-Install($id, $name, $extra) {
    if (-not (Have-Winget)) { Fail "$name is not installed and winget is unavailable. Install $name manually, then run start.bat again." }
    Info "Installing $name with winget (this can take a few minutes)..."
    $wargs = @("install", "-e", "--id", $id, "--silent", "--accept-package-agreements", "--accept-source-agreements") + $extra
    $p = Start-Process winget -ArgumentList $wargs -Wait -PassThru -NoNewWindow
    Refresh-Path
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne -1978335189) {  # -1978335189 = already installed
        Warn "winget returned exit code $($p.ExitCode) for $name"
    }
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor White
Write-Host "   ZENSAR  Content Studio  -  setup & launch" -ForegroundColor White
Write-Host "==============================================" -ForegroundColor White

# ---------------------------------------------------------------- already running?
try {
    $h = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
    if ($h.StatusCode -eq 200) {
        Ok "Content Studio is already running at $Url"
        if ($env:ZCS_NO_BROWSER -ne "1") { Start-Process $Url }
        exit 0
    }
} catch { }

# ---------------------------------------------------------------- 1. Python 3.10-3.12
Step 1 "Python"
function Test-Python($exe) {
    try {
        $v = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -match "^3\.(10|11|12)$") { return $true }
    } catch { }
    return $false
}
function Find-Python {
    foreach ($ver in @("3.12", "3.11", "3.10")) {
        try {
            $exe = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Python $exe)) { return $exe.Trim() }
        } catch { }
    }
    $cands = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe", "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe", "$env:ProgramFiles\Python310\python.exe")
    foreach ($c in $cands) { if ((Test-Path $c) -and (Test-Python $c)) { return $c } }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Python $cmd.Source)) { return $cmd.Source }
    return $null
}
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    $Py = Find-Python
    if (-not $Py) {
        Winget-Install "Python.Python.3.12" "Python 3.12" @("--scope", "user")
        $Py = Find-Python
        if (-not $Py) { Fail "Python 3.12 could not be installed automatically. Install it from https://www.python.org/downloads/ and run start.bat again." }
    }
    Ok "Using $Py"
    Info "Creating the private Python environment (.venv)..."
    & $Py -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) { Fail "Could not create the Python virtual environment." }
} else { Ok "Private Python environment present" }

# ---------------------------------------------------------------- 2. Python packages
Step 2 "Python packages"
$reqHash = File-Hash @((Join-Path $Root "requirements.txt"))
$reqMark = Join-Path $Root ".venv\.zcs_requirements"
if (-not (Test-Path $reqMark) -or (Get-Content $reqMark -Raw).Trim() -ne $reqHash) {
    Info "Installing packages (first run downloads ~300 MB)..."
    $pipLog = Join-Path $LogDir "pip.log"
    Run-Logged $VenvPy "-m pip install --upgrade pip --disable-pip-version-check -q" $pipLog | Out-Null
    $rc = Run-Logged $VenvPy "-m pip install -r `"$(Join-Path $Root 'requirements.txt')`" --disable-pip-version-check" $pipLog
    if ($rc -ne 0) { Fail "Python package installation failed (see logs\pip.log). Check the internet connection and try again." }
    Set-Content $reqMark $reqHash
    Ok "Packages installed"
} else { Ok "Packages up to date" }

# ---------------------------------------------------------------- 3. Configuration
Step 3 "Configuration"
$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Root ".env.example") $EnvFile; Ok "Created .env" } else { Ok ".env present" }

# ---------------------------------------------------------------- 4. Embedding model
Step 4 "Document understanding model"
$onnx = Join-Path $Root "models\embeddings\sentence-transformers__all-MiniLM-L6-v2\model.onnx"
if (-not (Test-Path $onnx)) {
    Info "Downloading the embedding model (~90 MB, one time)..."
    & $VenvPy (Join-Path $Root "scripts\fetch_models.py")
    if ($LASTEXITCODE -ne 0) { Fail "The embedding model could not be downloaded. Check the internet connection and try again." }
}
Ok "Embedding model ready"

# ---------------------------------------------------------------- 5. Node.js + interface
Step 5 "Web interface"
function Node-Ok {
    $n = Get-Command node -ErrorAction SilentlyContinue
    if (-not $n) { return $false }
    $v = (& node --version) -replace "^v", ""
    return ([int]($v.Split(".")[0]) -ge 18)
}
$front = Join-Path $Root "frontend"
$dist = Join-Path $front "dist\index.html"
$srcFiles = @(Get-ChildItem (Join-Path $front "src") -Recurse -File | Sort-Object FullName | ForEach-Object { $_.FullName })
$uiHash = File-Hash (@((Join-Path $front "package-lock.json"), (Join-Path $front "index.html"), (Join-Path $front "vite.config.ts")) + $srcFiles)
$uiMark = Join-Path $front "dist\.zcs_build"
$needBuild = -not (Test-Path $dist) -or -not (Test-Path $uiMark) -or ((Get-Content $uiMark -Raw).Trim() -ne $uiHash)
if ($needBuild) {
    if (-not (Node-Ok)) {
        Winget-Install "OpenJS.NodeJS.LTS" "Node.js LTS" @()
        $nodeDir = "$env:ProgramFiles\nodejs"
        if (Test-Path "$nodeDir\node.exe") { $env:Path = "$nodeDir;$env:Path" }
        if (-not (Node-Ok)) { Fail "Node.js 18+ could not be installed automatically. Install it from https://nodejs.org/ and run start.bat again." }
    }
    Ok "Node $(& node --version)"
    Push-Location $front
    try {
        Info "Installing interface packages..."
        $npmLog = Join-Path $LogDir "npm.log"
        $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
        if (-not $npm) { $npm = "npm.cmd" }
        $rc = Run-Logged $npm "ci --no-audit --no-fund" $npmLog
        if ($rc -ne 0) { $rc = Run-Logged $npm "install --no-audit --no-fund" $npmLog }
        if ($rc -ne 0) { Fail "Interface packages could not be installed (see logs\npm.log)." }
        Info "Building the interface..."
        $rc = Run-Logged $npm "run build" $npmLog
        if ($rc -ne 0 -or -not (Test-Path $dist)) { Fail "The interface build failed (see logs\npm.log)." }
    } finally { Pop-Location }
    Set-Content $uiMark $uiHash
    Ok "Interface built"
} else { Ok "Interface up to date" }

# ---------------------------------------------------------------- 6. Local AI (optional)
Step 6 "Local AI (optional)"
function Find-Ollama {
    $c = Get-Command ollama -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (Test-Path $p) { return $p }
    return $null
}
function Ollama-Models {
    try { return @((Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3).models | ForEach-Object { $_.name }) }
    catch { return $null }
}
if ($env:ZCS_SKIP_AI -eq "1") {
    Info "Skipped (ZCS_SKIP_AI=1). The app works in fast extractive mode without a local AI model."
} else {
    $ollama = Find-Ollama
    if (-not $ollama) {
        if (Ask "    Install Ollama (local AI runtime, free, ~1 GB) for AI-written slides?") {
            Winget-Install "Ollama.Ollama" "Ollama" @()
            $ollama = Find-Ollama
        }
    }
    if ($ollama) {
        $models = Ollama-Models
        if ($null -eq $models) {
            Info "Starting Ollama..."
            Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden
            for ($i = 0; $i -lt 20 -and $null -eq $models; $i++) { Start-Sleep 1; $models = Ollama-Models }
        }
        if ($null -eq $models) {
            Warn "Ollama is installed but not responding; AI writing will be available once Ollama is running."
        } else {
            if ($models.Count -eq 0) {
                if (Ask "    Download the recommended local model qwen2.5:3b (~2 GB, one time)?") {
                    & $ollama pull qwen2.5:3b
                    $models = Ollama-Models
                }
            }
            $envText = Get-Content $EnvFile -Raw
            if ($models -and $models.Count -gt 0 -and $envText -match "(?m)^OLLAMA_MODEL=\s*$") {
                $pick = ($models | Where-Object { $_ -like "qwen2.5:3b*" } | Select-Object -First 1)
                if (-not $pick) { $pick = ($models | Where-Object { $_ -like "qwen*" -or $_ -like "llama*" -or $_ -like "phi*" } | Select-Object -First 1) }
                if (-not $pick) { $pick = $models[0] }
                $envText = $envText -replace "(?m)^OLLAMA_MODEL=\s*$", "OLLAMA_MODEL=$pick"
                Set-Content $EnvFile $envText -NoNewline
                Ok "Local AI model: $pick"
            } elseif ($models -and $models.Count -gt 0) { Ok "Local AI ready ($($models.Count) model(s) installed)" }
            else { Warn "No local model installed; the app will use fast extractive mode." }
        }
    } else {
        Info "Not installed. The app works in fast extractive mode; install Ollama later for AI writing."
    }
}

# ---------------------------------------------------------------- 7. Check + launch
Step 7 "System check"
& $VenvPy (Join-Path $Root "scripts\check_environment.py")
if ($LASTEXITCODE -ne 0) { Fail "The system check reported a missing required component (see above)." }

Step 8 "Starting Content Studio"
$server = "`"$VenvPy`" backend\main.py 1>> logs\server.log 2>&1"
$env:BACKEND_PORT = "$Port"
Start-Process cmd -ArgumentList "/c", "title Zensar Content Studio (close to stop) && $server" -WorkingDirectory $Root -WindowStyle Minimized
$up = $false
for ($i = 0; $i -lt 90 -and -not $up; $i++) {
    Start-Sleep 1
    try { $up = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/health" -TimeoutSec 2).StatusCode -eq 200 } catch { }
}
if (-not $up) { Fail "The server did not start within 90 seconds (see logs\server.log)." }
Ok "Running at $Url"
if ($env:ZCS_NO_BROWSER -ne "1") { Start-Process $Url }
Write-Host ""
Write-Host "Content Studio is running at $Url" -ForegroundColor Green
Write-Host "Everything runs on this computer. To stop it, close the 'Zensar Content Studio' window (or run stop.bat)."
exit 0
