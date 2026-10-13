# Zensar Content Studio - one-click setup + launch (Windows 10/11 and Windows Server 2019/2022, PowerShell 5.1+).
# Called by start.bat. Safe to run repeatedly: every step is skipped when already done.
# Works without winget (Windows Server): Python, Node.js and Ollama are then downloaded from their official sites.
# On a machine with an NVIDIA GPU the GPU (CUDA) build of PyTorch is installed for image generation.
#
#   Environment switches (optional):
#     ZCS_SKIP_AI=1        do not offer to install Ollama / a local model
#     ZCS_SKIP_IMAGES=1    do not install local image generation (PyTorch + image model, ~5 GB)
#     ZCS_ASSUME_YES=1     answer "yes" to all prompts (unattended install)
#     ZCS_NO_BROWSER=1     do not open the browser
#     ZCS_PORT=8000        port for the server
#     ZCS_HOST=0.0.0.0     let other computers open the app (default 127.0.0.1 = this computer only)

# Native tools (pip/npm/ollama) write progress to stderr; in Windows PowerShell 5.1 that must not
# abort the script, so every step checks $LASTEXITCODE explicitly instead.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$env:PYTHONUTF8 = "1"            # log files and redirected output are always UTF-8
$env:PYTHONIOENCODING = "utf-8"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Port = if ($env:ZCS_PORT) { [int]$env:ZCS_PORT } else { 8000 }
$BindHost = if ($env:ZCS_HOST) { $env:ZCS_HOST } else { "127.0.0.1" }
$Url = "http://localhost:$Port"
# Windows Server's PowerShell 5.1 defaults to old TLS versions that python.org / nodejs.org refuse
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
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
function Download($url, $dest) {
    Info "Downloading $url"
    try { Invoke-WebRequest -UseBasicParsing $url -OutFile $dest -TimeoutSec 1800; return $true }
    catch { Warn "Download failed: $($_.Exception.Message)"; return $false }
}
# Without winget (Windows Server): official installers, silent, for the current user where possible
function Direct-Install($name) {
    $tmp = Join-Path $env:TEMP "zcs-setup"
    New-Item -ItemType Directory -Force $tmp | Out-Null
    switch ($name) {
        "Python 3.12" {
            $f = Join-Path $tmp "python-3.12.8-amd64.exe"
            if (Download "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe" $f) {
                Start-Process $f -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0" -Wait
            }
        }
        "Node.js LTS" {
            $f = Join-Path $tmp "node-v20.18.1-x64.msi"
            if (Download "https://nodejs.org/dist/v20.18.1/node-v20.18.1-x64.msi" $f) {
                Start-Process msiexec -ArgumentList "/i `"$f`" /qn /norestart" -Wait
            }
        }
        "Ollama" {
            $f = Join-Path $tmp "OllamaSetup.exe"
            if (Download "https://ollama.com/download/OllamaSetup.exe" $f) {
                Start-Process $f -ArgumentList "/VERYSILENT /NORESTART /SUPPRESSMSGBOXES" -Wait
            }
        }
    }
    Refresh-Path
}
function Winget-Install($id, $name, $extra) {
    if (-not (Have-Winget)) { Info "winget is not available - using the official $name installer"; Direct-Install $name; return }
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
# Content Studio answers /api/health with {"ok": true}; another program on the port is not mistaken for it.
function Probe($port) {
    try {
        $h = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/api/health" -TimeoutSec 3
        if ($h.Content -match '^\s*\{\s*"ok"\s*:\s*true\s*\}\s*$') { return "ours" }
        return "other"
    } catch {
        $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($busy) { return "other" } else { return "free" }
    }
}
$state = Probe $Port
if ($state -eq "ours") {
    Ok "Content Studio is already running at $Url"
    if ($env:ZCS_NO_BROWSER -ne "1") { Start-Process $Url }
    exit 0
}
if ($state -eq "other") {
    $orig = $Port
    for ($cand = $Port + 1; $cand -le $Port + 20; $cand++) {
        $st = Probe $cand
        if ($st -eq "ours") { $Url = "http://localhost:$cand"; Ok "Content Studio is already running at $Url"; if ($env:ZCS_NO_BROWSER -ne "1") { Start-Process $Url }; exit 0 }
        if ($st -eq "free") { $Port = $cand; break }
    }
    $Url = "http://localhost:$Port"
    Warn "Port $orig is used by another program - Content Studio will use port $Port"
}

# ---------------------------------------------------------------- 0. Visual C++ runtime (PyTorch / ONNX Runtime need it)
if (-not (Test-Path "$env:SystemRoot\System32\vcruntime140_1.dll")) {
    Step 0 "Microsoft Visual C++ runtime"
    $vc = Join-Path $env:TEMP "vc_redist.x64.exe"
    if (Download "https://aka.ms/vs/17/release/vc_redist.x64.exe" $vc) {
        Start-Process $vc -ArgumentList "/install /quiet /norestart" -Wait
        Ok "Visual C++ runtime installed"
    } else { Warn "Install the Visual C++ runtime (https://aka.ms/vs/17/release/vc_redist.x64.exe) if the app fails to start." }
}

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

# ---------------------------------------------------------------- GPU
$Gpu = $null; $GpuMemGB = 0
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if (-not $smi -and (Test-Path "$env:SystemRoot\System32\nvidia-smi.exe")) { $smi = Get-Command "$env:SystemRoot\System32\nvidia-smi.exe" }
if ($smi) {
    try {
        $q = (& $smi.Source --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
        if ($q) { $parts = $q.Split(","); $Gpu = $parts[0].Trim(); $GpuMemGB = [math]::Round([double]$parts[1].Trim() / 1024, 1) }
    } catch { }
}

# ---------------------------------------------------------------- 6. Image generation (Brand Documents)
Step 6 "Image generation (Brand Documents)"
if ($env:ZCS_SKIP_IMAGES -eq "1") {
    Info "Skipped (ZCS_SKIP_IMAGES=1). Brand documents use brand-coloured artwork instead of generated images."
} else {
    $flavour = if ($Gpu) { "cu124" } else { "cpu" }
    $imgMark = Join-Path $Root ".venv\.zcs_images"
    $imgHash = "$flavour|" + (File-Hash @((Join-Path $Root "requirements-images.txt")))
    $haveImg = (Test-Path $imgMark) -and ((Get-Content $imgMark -Raw).Trim() -eq $imgHash)
    if (-not $haveImg) {
        $what = if ($Gpu) { "GPU build for $Gpu, ~2.5 GB" } else { "CPU build, ~250 MB - no NVIDIA GPU found" }
        if (Ask "    Install PyTorch for local image generation ($what)?") {
            $pipLog = Join-Path $LogDir "pip.log"
            Info "Installing PyTorch ($flavour)..."
            $rc = Run-Logged $VenvPy "-m pip install torch --index-url https://download.pytorch.org/whl/$flavour --disable-pip-version-check" $pipLog
            if ($rc -eq 0) {
                $rc = Run-Logged $VenvPy "-m pip install -r `"$(Join-Path $Root 'requirements-images.txt')`" --disable-pip-version-check" $pipLog
            }
            if ($rc -eq 0) { Set-Content $imgMark $imgHash; Ok "Image libraries installed" }
            else { Warn "Image libraries could not be installed (see logs\pip.log); brand documents will use artwork instead." }
        }
    } else { Ok "Image libraries present ($flavour)" }
    $ckpt = Join-Path $Root "models\imagegen\dreamshaper-8-lcm\DreamShaper8_LCM.safetensors"
    if ((Test-Path $imgMark) -and -not (Test-Path $ckpt)) {
        if (Ask "    Download the image model DreamShaper 8 LCM (~2.2 GB, one time)?") {
            & $VenvPy (Join-Path $Root "scripts\fetch_models.py") --images
            if ($LASTEXITCODE -ne 0) { Warn "The image model could not be downloaded; run start.bat again later." }
        }
    }
    if (Test-Path $ckpt) {
        $where = if ($Gpu) { "GPU: $Gpu, $GpuMemGB GB" } else { "CPU" }
        Ok "Image model ready ($where)"
    }
}

# ---------------------------------------------------------------- 7. Local AI (optional)
Step 7 "Local AI (optional)"
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
            # a GPU with 8 GB or more runs the 7B model quickly (better writing); otherwise the 3B model
            $want = if ($GpuMemGB -ge 7.5) { "qwen2.5:7b" } else { "qwen2.5:3b" }
            if (-not ($models | Where-Object { $_ -like "$want*" -or ($want -eq "qwen2.5:7b" -and $_ -like "qwen2.5:latest") })) {
                $size = if ($want -eq "qwen2.5:7b") { "~4.7 GB" } else { "~2 GB" }
                if (Ask "    Download the recommended local model $want ($size, one time)?") {
                    & $ollama pull $want
                    $models = Ollama-Models
                }
            }
            if ($models -and $models.Count -gt 0 -and -not ($models | Where-Object { $_ -match "vl|llava|moondream|vision" })) {
                if (Ask "    Download the vision model qwen2.5vl:3b (~3.2 GB, one time) so demo videos are understood frame by frame?") {
                    & $ollama pull qwen2.5vl:3b
                    $models = Ollama-Models
                }
            }
            $envText = Get-Content $EnvFile -Raw
            if ($models -and $models.Count -gt 0 -and $envText -match "(?m)^OLLAMA_MODEL=\s*$") {
                $pick = ($models | Where-Object { $_ -like "$want*" } | Select-Object -First 1)
                $text = @($models | Where-Object { $_ -notmatch "vl|llava|moondream|vision" })  # vision models only describe frames
                if (-not $pick) { $pick = ($text | Where-Object { $_ -like "qwen*" -or $_ -like "llama*" -or $_ -like "phi*" } | Select-Object -First 1) }
                if (-not $pick -and $text.Count -gt 0) { $pick = $text[0] }
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
Step 8 "System check"
& $VenvPy (Join-Path $Root "scripts\check_environment.py")
if ($LASTEXITCODE -ne 0) { Fail "The system check reported a missing required component (see above)." }

Step 9 "Starting Content Studio"
$server = "`"$VenvPy`" backend\main.py 1>> logs\server.log 2>&1"
$env:BACKEND_PORT = "$Port"
$env:BACKEND_HOST = $BindHost
if ($BindHost -ne "127.0.0.1" -and $BindHost -ne "localhost") {
    # other computers may open the app: allow the port through Windows Firewall (needs an administrator prompt)
    $rule = "Zensar Content Studio $Port"
    if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
        try { New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -ErrorAction Stop | Out-Null; Ok "Firewall: port $Port opened" }
        catch { Warn "Could not open port $Port in Windows Firewall (run start.bat as administrator once, or open it in the cloud firewall)." }
    }
    Warn "The app has no login: allow only your own IP address in the cloud firewall / security group."
}
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
if ($BindHost -ne "127.0.0.1" -and $BindHost -ne "localhost") {
    $ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } | ForEach-Object { $_.IPAddress })
    foreach ($ip in $ips) { Write-Host "From another computer: http://${ip}:$Port  (or the server's public IP)" -ForegroundColor Green }
}
Write-Host "Everything runs on this computer. To stop it, close the 'Zensar Content Studio' window (or run stop.bat)."
exit 0
