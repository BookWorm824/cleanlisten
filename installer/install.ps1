# CleanListen installer (Windows 10/11). Run via "Install CleanListen.bat".
# Installs into %LOCALAPPDATA%\CleanListen. No admin rights needed.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root   = Join-Path $env:LOCALAPPDATA 'CleanListen'
$AppDir = Join-Path $Root 'app'
$Venv   = Join-Path $Root 'venv'
$Tmp    = Join-Path $Root 'downloads'
$ModelName = 'sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8'
$ModelUrl  = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$ModelName.tar.bz2"
$FfmpegUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'
$PyInstallerUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'

function Step($n, $text) { Write-Host ""; Write-Host "[$n/6] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "      $text" -ForegroundColor Green }
function Fail($text) { throw $text }

function Download($url, $dest) {
    # curl.exe ships with Windows 10+ and is much faster than Invoke-WebRequest
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (Test-Path $curl) {
        & $curl -L --fail --retry 3 -o $dest $url
        if ($LASTEXITCODE -ne 0) { Fail "Download failed: $url" }
    } else {
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    }
}

function Find-Python {
    # A Python 3.11-3.13 that includes tkinter (the window toolkit)
    $check = 'import sys, tkinter; print(sys.executable)'
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($v in '3.12', '3.13', '3.11') {
            try {
                $exe = (& py "-$v" -c $check 2>$null | Select-Object -Last 1)
                if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe)) { return $exe.Trim() }
            } catch {}
        }
    }
    foreach ($v in '312', '313', '311') {
        $exe = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"
        if (Test-Path $exe) {
            try {
                & $exe -c $check *> $null
                if ($LASTEXITCODE -eq 0) { return $exe }
            } catch {}
        }
    }
    return $null
}

try {
    Write-Host "CleanListen setup" -ForegroundColor White
    Write-Host "This downloads about 700 MB and takes 5-15 minutes. Leave this window open."
    New-Item -ItemType Directory -Force -Path $Root, $AppDir, $Tmp | Out-Null

    # 1. app files
    Step 1 "Copying CleanListen..."
    if (-not (Test-Path (Join-Path $PSScriptRoot 'app\CleanListen.pyw'))) {
        Fail "Setup files are missing. Right-click the zip, choose 'Extract All', and run setup from the extracted folder."
    }
    Copy-Item -Path (Join-Path $PSScriptRoot 'app\*') -Destination $AppDir -Recurse -Force
    Ok "Done"

    # 2. Python
    Step 2 "Checking for Python..."
    $python = Find-Python
    if (-not $python) {
        Write-Host "      Python not found - installing Python 3.12 (just for you, no admin needed)..."
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if ($winget) {
            & winget install -e --id Python.Python.3.12 --scope user --silent `
                --accept-package-agreements --accept-source-agreements | Out-Host
            $python = Find-Python
        }
        if (-not $python) {
            $inst = Join-Path $Tmp 'python-installer.exe'
            Download $PyInstallerUrl $inst
            Start-Process -FilePath $inst -Wait -ArgumentList `
                '/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_tcltk=1', `
                'Include_launcher=1', 'Include_test=0', 'Shortcuts=0'
            $python = Find-Python
        }
        if (-not $python) { Fail "Couldn't install Python automatically. Install Python 3.12 from python.org, then run this setup again." }
    }
    Ok "Using $python"

    # 3. private Python environment + libraries
    Step 3 "Installing the speech-recognition libraries..."
    if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
        & $python -m venv $Venv
        if ($LASTEXITCODE -ne 0) { Fail "Couldn't create the Python environment." }
    }
    $vpy = Join-Path $Venv 'Scripts\python.exe'
    & $vpy -m pip install --upgrade pip --quiet --disable-pip-version-check
    & $vpy -m pip install --quiet --disable-pip-version-check sherpa-onnx numpy beautifulsoup4 pypdf
    if ($LASTEXITCODE -ne 0) { Fail "Installing libraries failed. Check your internet connection and run setup again." }
    & $vpy -c "import sherpa_onnx, numpy, bs4, tkinter"
    if ($LASTEXITCODE -ne 0) { Fail "Libraries installed but won't load." }
    Ok "Done"

    # 4. ffmpeg (reads and writes the audio files)
    Step 4 "Getting the audio tools (ffmpeg)..."
    $bin = Join-Path $AppDir 'bin'
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    if (-not (Test-Path (Join-Path $bin 'ffmpeg.exe'))) {
        $zip = Join-Path $Tmp 'ffmpeg.zip'
        Download $FfmpegUrl $zip
        $x = Join-Path $Tmp 'ffmpeg'
        if (Test-Path $x) { Remove-Item $x -Recurse -Force }
        Expand-Archive -Path $zip -DestinationPath $x -Force
        foreach ($exe in 'ffmpeg.exe', 'ffprobe.exe') {
            $f = Get-ChildItem -Path $x -Recurse -Filter $exe | Select-Object -First 1
            if (-not $f) { Fail "ffmpeg download looked wrong (no $exe)." }
            Copy-Item $f.FullName (Join-Path $bin $exe) -Force
        }
        Remove-Item $zip, $x -Recurse -Force -ErrorAction SilentlyContinue
    }
    Ok "Done"

    # 5. speech model
    Step 5 "Downloading the listening model (about 480 MB)..."
    $models = Join-Path $AppDir 'models'
    New-Item -ItemType Directory -Force -Path $models | Out-Null
    if (-not (Test-Path (Join-Path $models "$ModelName\encoder.int8.onnx"))) {
        $tarball = Join-Path $Tmp 'model.tar.bz2'
        Download $ModelUrl $tarball
        Write-Host "      Unpacking..."
        & (Join-Path $env:SystemRoot 'System32\tar.exe') -xjf $tarball -C $models
        if ($LASTEXITCODE -ne 0) { Fail "Couldn't unpack the model." }
        Remove-Item $tarball -Force -ErrorAction SilentlyContinue
    }
    Ok "Done"

    # 6. shortcuts
    Step 6 "Adding CleanListen to your Desktop and Start menu..."
    $pyw = Join-Path $Venv 'Scripts\pythonw.exe'
    $script = Join-Path $AppDir 'launcher.pyw'   # checks GitHub for updates, then opens the app
    $icon = Join-Path $AppDir 'icon.ico'
    $shell = New-Object -ComObject WScript.Shell
    $places = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
    foreach ($dir in $places) {
        $lnk = $shell.CreateShortcut((Join-Path $dir 'CleanListen.lnk'))
        $lnk.TargetPath = $pyw
        $lnk.Arguments = "`"$script`""
        $lnk.WorkingDirectory = $AppDir
        $lnk.IconLocation = $icon
        $lnk.Description = 'Clean up audiobooks'
        $lnk.Save()
    }
    Ok "Done"

    Write-Host ""
    Write-Host "All set! CleanListen is on your Desktop. Opening it now..." -ForegroundColor Green
    Start-Process -FilePath $pyw -ArgumentList "`"$script`"" -WorkingDirectory $AppDir
    exit 0
}
catch {
    Write-Host ""
    Write-Host "Setup stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Nothing is broken - you can run setup again and it will pick up where it left off."
    exit 1
}
