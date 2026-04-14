@echo off
REM ============================================================
REM  PerkySue - Portable Installer v3.0
REM  Installs Python, detects GPU FIRST, then installs packages
REM  with CUDA-accelerated STT when NVIDIA is detected.
REM  English version for international market
REM ============================================================
REM  CHANGE LOG v2.5 → v3.0:
REM    - GPU detection moved BEFORE package installation
REM    - faster-whisper install is now CUDA-aware (installs
REM      nvidia-cublas-cu12 + nvidia-cudnn-cu12 for NVIDIA)
REM    - Step numbering updated (8 steps → 8 steps, reordered)
REM    - Verification step: ctranslate2 CUDA check after install
REM  v3.0 → v3.1: Step 7b — Deploy VC++ runtime (portable) from
REM    Assets\vcredist-x64-portable.zip into each existing backend folder.
REM  v3.1 → v3.2: llama-cpp-python — pip download cache for CPU; NVIDIA uses
REM    PyPI win_amd64 wheel (no official CUDA win wheel for 0.3.16 on abetlen).
REM    Step 7 — auto-download + extract llama-server from GitHub releases;
REM    cache under Data\Cache\.
REM  v3.2 → v3.3: Step 1 — embedded Python zip from Assets, Data\Cache, or
REM    auto-download to Data\Cache (no browser); extract to Python\ (portable).
REM  v3.3 → v3.4: Desktop shortcut (PerkySue.lnk) after successful install.
REM  v3.4 → v3.5: RTX 50xx → try llama.cpp CUDA 13.1 zips, fallback 12.4 on failure;
REM    shortcut uses PerkySue.ico when present at repo root.
REM  v3.5 → v3.6: RTX 50xx — use 13.1 zips only if nvidia-smi "CUDA Version" is 13+;
REM    else 12.4 directly (driver must expose CUDA 13.x for 13.1 runtimes). See
REM    App\tools\driver_supports_cuda13.ps1
REM ============================================================
cd /d "%~dp0"
setlocal enabledelayedexpansion

set "APP_DIR=%~dp0"
set "PYTHON_DIR=%APP_DIR%Python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "DATA_DIR=%APP_DIR%Data"
set "TOOLS_DIR=%DATA_DIR%\Tools"
set "SCRIPTS_DIR=%PYTHON_DIR%\Scripts"
set "PIP_EXE=%SCRIPTS_DIR%\pip.exe"

REM ============================================================
REM  llama.cpp release - change this ONE variable to update
REM  Check https://github.com/ggml-org/llama.cpp/releases   
REM ============================================================
set "LLAMA_VER=b8188"

echo.
echo  =============================================
echo   PerkySue - Installer v3.6
echo  =============================================
echo  Working dir: %CD%
echo.

REM ===========================================
REM  STEP 1: Check/Install Python (embed 3.11.9 amd64)
REM  Priority: Assets\ → Data\Cache\ → download to Data\Cache\
REM  Legacy: python-embed.zip or python-3.11.9-embed-amd64.zip in install root
REM ===========================================
if exist "%PYTHON_EXE%" (
    echo  [OK] Python already installed.
    goto :check_pip
)

set "PY_ZIP_NAME=python-3.11.9-embed-amd64.zip"
set "PY_ZIP_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
set "PY_ZIP_ASSETS=%APP_DIR%Assets\%PY_ZIP_NAME%"
set "PY_ZIP_CACHE=%DATA_DIR%\Cache\%PY_ZIP_NAME%"

if not exist "%DATA_DIR%\Cache" mkdir "%DATA_DIR%\Cache"

echo  Python not found. Locating embedded runtime zip...
echo.

if exist "%PY_ZIP_ASSETS%" (
    set "PYTHON_ZIP_PATH=%PY_ZIP_ASSETS%"
    echo  [OK] Using bundled zip: Assets\%PY_ZIP_NAME%
    goto :extract_python
)
if exist "%PY_ZIP_CACHE%" (
    set "PYTHON_ZIP_PATH=%PY_ZIP_CACHE%"
    echo  [OK] Using cached zip: Data\Cache\%PY_ZIP_NAME%
    goto :extract_python
)
if exist "%APP_DIR%python-embed.zip" (
    set "PYTHON_ZIP_PATH=%APP_DIR%python-embed.zip"
    echo  [OK] Found legacy: python-embed.zip in install folder
    goto :extract_python
)
if exist "%APP_DIR%%PY_ZIP_NAME%" (
    set "PYTHON_ZIP_PATH=%APP_DIR%%PY_ZIP_NAME%"
    echo  [OK] Found: %PY_ZIP_NAME% in install folder
    goto :extract_python
)

echo  Downloading %PY_ZIP_NAME% from python.org...
echo  Saving to: Data\Cache\ ^(reused on next run^)
echo.

set "PERKYSUE_PY_CACHE=%DATA_DIR%\Cache"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $ProgressPreference='SilentlyContinue'; $u='%PY_ZIP_URL%'; $p=Join-Path $env:PERKYSUE_PY_CACHE '%PY_ZIP_NAME%'; Invoke-WebRequest -Uri $u -OutFile $p -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
    echo  [ERROR] Download failed. Check network / firewall / TLS.
    echo  URL: %PY_ZIP_URL%
    pause
    exit /b 1
)
if not exist "%PY_ZIP_CACHE%" (
    echo  [ERROR] Download finished but file is missing.
    pause
    exit /b 1
)
set "PYTHON_ZIP_PATH=%PY_ZIP_CACHE%"
echo  [OK] Download complete.
echo.

:extract_python
echo  Extracting to "%PYTHON_DIR%"...

if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"

tar -xf "%PYTHON_ZIP_PATH%" -C "%PYTHON_DIR%" 2>nul
if errorlevel 1 (
    echo  tar failed, trying PowerShell...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%PYTHON_ZIP_PATH%' -DestinationPath '%PYTHON_DIR%' -Force"
    if errorlevel 1 (
        echo  [ERROR] Extraction failed!
        pause
        exit /b 1
    )
)

if not exist "%PYTHON_EXE%" (
    echo  [ERROR] Extraction seemed to work but python.exe not found!
    pause
    exit /b 1
)

echo  [OK] Python extracted successfully.
REM Keep zip in Data\Cache or Assets; do not delete — speeds reinstall / offline use.
echo.

REM ===========================================
REM  STEP 2: Install pip for embedded Python
REM ===========================================
:check_pip
if exist "%PIP_EXE%" (
    echo  [OK] pip already installed.
) else (
    echo  Installing pip...
    echo.

    REM Download get-pip.py
    powershell -Command "(New-Object Net.WebClient).DownloadFile('https://bootstrap.pypa.io/get-pip.py', '%APP_DIR%get-pip.py')" 2>nul

    if not exist "%APP_DIR%get-pip.py" (
        echo  [ERROR] Failed to download get-pip.py
        echo  Download manually from: https://bootstrap.pypa.io/get-pip.py
        pause
        exit /b 1
    )

    REM Configure Python: site-packages + Lib/DLLs for tkinter
    for %%f in ("%PYTHON_DIR%\python*._pth") do (
        echo python311.zip > "%%f"
        echo . >> "%%f"
        echo Lib >> "%%f"
        echo DLLs >> "%%f"
        echo Lib\site-packages >> "%%f"
        echo import site >> "%%f"
    )

    REM Install pip
    "%PYTHON_EXE%" "%APP_DIR%get-pip.py" --no-warn-script-location
    del "%APP_DIR%get-pip.py" 2>nul

    if not exist "%PIP_EXE%" (
        echo  [ERROR] pip installation failed!
        pause
        exit /b 1
    )
    echo  [OK] pip installed.
    echo.
)

REM ===========================================
REM  STEP 2b: Install tkinter for GUI support
REM  ZIP root: DLLs/, Lib/tkinter/, tcl/ - extract to Python/
REM ===========================================
echo  Checking tkinter for GUI support...

if exist "%PYTHON_DIR%\Lib\tkinter\__init__.py" goto :tkinter_done
echo  Installing tkinter from local package...
set "TK_ZIP=%APP_DIR%Assets\tkinter-3.11-embed.zip"
if not exist "!TK_ZIP!" goto :tkinter_warn
if not exist "%PYTHON_DIR%\Lib" mkdir "%PYTHON_DIR%\Lib"
if not exist "%PYTHON_DIR%\DLLs" mkdir "%PYTHON_DIR%\DLLs"
echo  Extracting to: %PYTHON_DIR%
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '!TK_ZIP!' -DestinationPath '!PYTHON_DIR!' -Force"
if !errorlevel! neq 0 (
    echo  PowerShell failed, trying tar...
    tar -xf "!TK_ZIP!" -C "%PYTHON_DIR%"
)
if exist "%PYTHON_DIR%\Lib\tkinter\__init__.py" (
    echo  [OK] tkinter installed for GUI support.
) else (
    echo  [ERROR] tkinter extraction failed or files in wrong place.
)
goto :tkinter_done
:tkinter_warn
echo  [WARNING] tkinter package not found in Assets/
echo     Expected: Assets\tkinter-3.11-embed.zip
echo     GUI will not be available (console mode only).
:tkinter_done
REM Ensure ._pth includes Lib and DLLs so Python finds tkinter (required when pip was already installed)
for %%f in ("%PYTHON_DIR%\python*._pth") do (
    echo python311.zip > "%%f"
    echo . >> "%%f"
    echo Lib >> "%%f"
    echo DLLs >> "%%f"
    echo Lib\site-packages >> "%%f"
    echo import site >> "%%f"
)
echo.

REM ===========================================
REM  STEP 3: Create directory structure
REM ===========================================
:create_folders
echo  Creating directories...

for %%d in (
    "%DATA_DIR%"
    "%DATA_DIR%\Models"
    "%DATA_DIR%\Models\Whisper"
    "%DATA_DIR%\Models\LLM"
    "%DATA_DIR%\Models\TTS"
    "%DATA_DIR%\HuggingFace"
    "%DATA_DIR%\Audio"
    "%DATA_DIR%\Cache"
    "%DATA_DIR%\Cache\wheels"
    "%DATA_DIR%\Cache\llama-backend"
    "%DATA_DIR%\Logs"
    "%DATA_DIR%\Configs"
    "%DATA_DIR%\Formatting"
    "%DATA_DIR%\Benchmarks"
    "%DATA_DIR%\Native"
    "%TOOLS_DIR%"
    "%TOOLS_DIR%\nvidia-cuda-12.4"
    "%TOOLS_DIR%\nvidia-cuda-13.1"
    "%TOOLS_DIR%\vulkan"
    "%TOOLS_DIR%\cpu"
) do (
    if not exist %%d mkdir %%d
)

echo  [OK] Directories created.

REM ===========================================
REM  STEP 4: Detect GPU hardware
REM  (Moved BEFORE package install so that
REM   STT can be installed with CUDA support)
REM ===========================================
echo.
echo  =============================================
echo   Hardware Detection
echo  =============================================
echo.

set "BACKEND=cpu"
set "GPU_NAME=No dedicated GPU"

REM --- Check for NVIDIA ---
where nvidia-smi >nul 2>&1
if !errorlevel! neq 0 goto :check_amd

REM nvidia-smi exists = NVIDIA hardware confirmed
REM Use temp file to avoid crash: for /f in ('nvidia-smi') can hang or break on ! in GPU name
set "NVFILE=%TEMP%\perkysue_nv_%RANDOM%.txt"
nvidia-smi -L > "%NVFILE%" 2>nul
setlocal disabledelayedexpansion
set "GPU_NAME=No dedicated GPU"
if exist "%NVFILE%" (
    for /f "usebackq tokens=1,* delims=:" %%a in ("%NVFILE%") do (
        for /f "tokens=* delims= " %%z in ("%%b") do set "GPU_NAME=%%z"
    )
    del "%NVFILE%" 2>nul
)
endlocal & set "GPU_NAME=%GPU_NAME%"

REM Detect NVIDIA family — RTX 50xx: llama.cpp 13.1 zips only if driver reports CUDA 13+ (nvidia-smi); else 12.4
REM Other RTX: CUDA 12.4. Whisper STT still uses pip CUDA12 stack regardless.
set "G=!GPU_NAME!"
if not "!G:RTX 50=!"=="!G!" goto :set_nvidia_rtx50_cuda
if not "!G:5060=!"=="!G!" goto :set_nvidia_rtx50_cuda
if not "!G:5070=!"=="!G!" goto :set_nvidia_rtx50_cuda
if not "!G:5080=!"=="!G!" goto :set_nvidia_rtx50_cuda
if not "!G:5090=!"=="!G!" goto :set_nvidia_rtx50_cuda
if not "!G:RTX 40=!"=="!G!" goto :set_nvidia_12_4
if not "!G:4070=!"=="!G!" goto :set_nvidia_12_4
if not "!G:4080=!"=="!G!" goto :set_nvidia_12_4
if not "!G:4090=!"=="!G!" goto :set_nvidia_12_4
if not "!G:RTX 30=!"=="!G!" goto :set_nvidia_12_4
if not "!G:3060=!"=="!G!" goto :set_nvidia_12_4
if not "!G:3070=!"=="!G!" goto :set_nvidia_12_4
if not "!G:3080=!"=="!G!" goto :set_nvidia_12_4
if not "!G:3090=!"=="!G!" goto :set_nvidia_12_4
if not "!G:RTX 20=!"=="!G!" goto :set_nvidia_12_4
if not "!G:2060=!"=="!G!" goto :set_nvidia_12_4
if not "!G:2070=!"=="!G!" goto :set_nvidia_12_4
if not "!G:2080=!"=="!G!" goto :set_nvidia_12_4
goto :set_nvidia_fallback
:set_nvidia_rtx50_cuda
echo  [GPU] NVIDIA GPU detected: !GPU_NAME!
echo  [GPU] RTX 50xx — checking driver CUDA capability ^(nvidia-smi header^)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%App\tools\driver_supports_cuda13.ps1" 2>nul
if errorlevel 1 (
    set "BACKEND=nvidia-cuda-12.4"
    echo  [GPU] Driver CUDA max is 12.x or unknown — using llama.cpp 12.4 ^(CUDA 13.1 needs driver reporting CUDA 13+^).
    goto :gpu_done
)
set "BACKEND=nvidia-cuda-13.1"
echo  [GPU] Driver reports CUDA 13.x capable — using llama.cpp 13.1 ^(Step 7 falls back to 12.4 if download fails^).
goto :gpu_done
:set_nvidia_12_4
set "BACKEND=nvidia-cuda-12.4"
echo  [GPU] NVIDIA GPU detected: !GPU_NAME!
echo  [GPU] Using CUDA 12.4 backend
goto :gpu_done
:set_nvidia_fallback
REM Other NVIDIA (GTX, older) → CUDA 12.4 fallback
set "BACKEND=nvidia-cuda-12.4"
echo  [GPU] NVIDIA GPU detected: !GPU_NAME!
echo  [GPU] Using CUDA 12.4 backend (fallback)
goto :gpu_done

REM --- Check for AMD ---
:check_amd
reg query "HKLM\SYSTEM\CurrentControlSet\Control\Video" /s /f "AMD" >nul 2>&1
if !errorlevel! equ 0 (
    set "GPU_NAME=AMD GPU"
    set "BACKEND=vulkan"
    echo  [GPU] AMD detected - Vulkan backend
    goto :gpu_done
)
goto :check_intel

REM --- Check for Intel ---
:check_intel
reg query "HKLM\SYSTEM\CurrentControlSet\Control\Video" /s /f "Intel" >nul 2>&1
if !errorlevel! equ 0 (
    set "GPU_NAME=Intel GPU"
    set "BACKEND=vulkan"
    echo  [GPU] Intel detected - Vulkan backend
    goto :gpu_done
)

REM --- No GPU detected - CPU fallback ---
:check_cpu
set "BACKEND=cpu"
echo  [GPU] No dedicated GPU - CPU backend

:gpu_done
echo.
echo  Selected backend: !BACKEND!
echo.

REM ===========================================
REM  STEP 5: Install Python packages
REM  (BACKEND is now known — STT install is
REM   CUDA-aware for NVIDIA users)
REM ===========================================
echo  Installing Python packages...
echo  (This may take a few minutes)
echo.

set "HF_HOME=%DATA_DIR%\HuggingFace"
set "TRANSFORMERS_CACHE=%DATA_DIR%\HuggingFace"
set "XDG_CACHE_HOME=%DATA_DIR%\Cache"

echo  [1/6] Core packages (pyyaml, numpy, httpx, pyperclip, pynput, cryptography)...
"%PYTHON_EXE%" -m pip install --no-warn-script-location pyyaml numpy httpx pyperclip pynput cryptography
if errorlevel 1 echo  [WARNING] Some core packages failed

echo.
echo  [2/6] Audio processing (sounddevice, webrtcvad, pygame)...
"%PYTHON_EXE%" -m pip install --no-warn-script-location sounddevice PyAudioWPatch webrtcvad-wheels pygame
if errorlevel 1 echo  [WARNING] Some audio packages failed

echo.
echo  [3/6] Speech-to-Text engine (faster-whisper)...
if "!BACKEND!"=="nvidia-cuda-12.4" goto :stt_nvidia
if "!BACKEND!"=="nvidia-cuda-13.1" goto :stt_nvidia
goto :stt_cpu

:stt_nvidia
set "STT_ACCEL=CUDA"
echo        NVIDIA detected — installing CUDA-accelerated STT...
echo        (this downloads ~800 MB of CUDA libraries, please wait)
REM Wheel-only: avoid pip building nvidia-* from sdist (wheel_stub errors on reinstall)
"%PYTHON_EXE%" -m pip install --no-warn-script-location --only-binary=:all: nvidia-cublas-cu12 nvidia-cudnn-cu12
if errorlevel 1 (
    echo        [WARNING] CUDA math libs install had issues — trying without strict wheel-only...
    "%PYTHON_EXE%" -m pip install --no-warn-script-location nvidia-cublas-cu12 nvidia-cudnn-cu12
)
"%PYTHON_EXE%" -m pip install --no-warn-script-location ctranslate2 faster-whisper
echo.
echo        Verifying CUDA support for Whisper...
"%PYTHON_EXE%" -c "import ctranslate2; t=ctranslate2.get_supported_compute_types('cuda'); exit(0 if t else 1)"
if errorlevel 1 (
    echo        ctranslate2 reports no CUDA ^(CPU-only wheel^). Reinstalling ctranslate2...
    "%PYTHON_EXE%" -m pip uninstall ctranslate2 -y
    "%PYTHON_EXE%" -m pip install --no-warn-script-location ctranslate2
    "%PYTHON_EXE%" -c "import ctranslate2; t=ctranslate2.get_supported_compute_types('cuda'); exit(0 if t else 1)"
    if errorlevel 1 (
        echo        [WARNING] Still no CUDA after reinstall. Whisper will use CPU at startup.
    ) else (
        echo        [OK] CUDA support verified after reinstall.
    )
) else (
    echo        [OK] CUDA support verified.
)
goto :stt_done

:stt_cpu
set "STT_ACCEL=CPU"
echo        Installing CPU version (no NVIDIA GPU detected)...
"%PYTHON_EXE%" -m pip install --no-warn-script-location faster-whisper
goto :stt_done

:stt_done
echo.
echo  [4/6] GUI and API clients (customtkinter, pillow, requests, huggingface-hub, openai, psutil)...
"%PYTHON_EXE%" -m pip install --no-warn-script-location customtkinter pillow requests huggingface-hub openai psutil

echo.
echo  [5/6] LLM library ^(llama-cpp-python — for direct mode only; llama-server.exe does not need it^)...
REM On non-CPU / non-NVIDIA backends (e.g. Vulkan AMD/Intel), direct mode is not required.
REM Skip llama-cpp-python there to avoid huge downloads and resolver backtracking loops.
if /I not "%BACKEND%"=="cpu" if /I not "%BACKEND%"=="nvidia-cuda-12.4" if /I not "%BACKEND%"=="nvidia-cuda-13.1" (
    echo        Skipping llama-cpp-python for backend %BACKEND% ^(server mode only^).
    goto :after_llama_cpp
)
set "WHEEL_CACHE=%DATA_DIR%\Cache\wheels"
if "!BACKEND!"=="cpu" (
    echo        Caching CPU wheel ^(pip download to Data\Cache\wheels^)...
    "%PYTHON_EXE%" -m pip download --only-binary=:all: --no-deps -d "!WHEEL_CACHE!" "llama-cpp-python==0.3.16"
    if not errorlevel 1 (
        "%PYTHON_EXE%" -m pip install --no-warn-script-location --no-index --find-links "!WHEEL_CACHE!" "llama-cpp-python==0.3.16"
    ) else (
        echo        [INFO] pip download cache failed, installing from PyPI...
        "%PYTHON_EXE%" -m pip install --no-warn-script-location "llama-cpp-python==0.3.16"
    )
) else (
    REM NVIDIA: official cu124 wheels on abetlen are Linux-only for 0.3.16; use PyPI win_amd64 wheel.
    echo        Installing llama-cpp-python from PyPI ^(Windows; GPU LLM uses llama-server^)...
    "%PYTHON_EXE%" -m pip install --no-warn-script-location "llama-cpp-python==0.3.16"
)
if errorlevel 1 (
    echo        First attempt failed, trying with build dependencies...
    "%PYTHON_EXE%" -m pip install --no-warn-script-location scikit-build-core cmake
    "%PYTHON_EXE%" -m pip install --no-warn-script-location "llama-cpp-python==0.3.16"
)
if errorlevel 1 (
    echo        [WARNING] llama-cpp-python could not be installed ^(build failed or network issue^).
    echo        PerkySue will use server mode ^(llama-server.exe^) — no action needed.
    echo        For direct mode later: pip install scikit-build-core cmake then llama-cpp-python.
)

:after_llama_cpp
echo.
echo  [6/6] Verifying installation...
"%PYTHON_EXE%" -c "import faster_whisper; print('  [OK] faster-whisper')"
"%PYTHON_EXE%" -c "import customtkinter; print('  [OK] customtkinter')"
"%PYTHON_EXE%" -c "import yaml; print('  [OK] pyyaml')"

echo.
echo  [OK] Python packages installed.

REM ===========================================
REM  STEP 6: Note about Whisper model
REM ===========================================
echo.
echo  =============================================
echo   Note: Whisper Model
echo  =============================================
echo.
echo  The Whisper model (~1.5 GB) will be downloaded
echo  automatically when you first run PerkySue.
echo  No action needed now.
echo.
if "!BACKEND!"=="nvidia-cuda-12.4" (
    echo  Your NVIDIA GPU will accelerate Whisper transcription.
    echo  Expected: "Whisper: GPU (CUDA)" at startup.
)
if "!BACKEND!"=="nvidia-cuda-13.1" (
    echo  Your NVIDIA GPU will accelerate Whisper transcription.
    echo  Expected: "Whisper: GPU (CUDA)" at startup.
)
if "!BACKEND!"=="vulkan" (
    echo  Note: Whisper uses CPU even with AMD/Intel GPU.
    echo  Vulkan is used for LLM only. This is normal.
)
if "!BACKEND!"=="cpu" (
    echo  Whisper will run on CPU. Transcription may be slower.
)
echo.

REM ===========================================
REM  STEP 7: Backend (llama-server) — auto-download from GitHub
REM  See App\tools\install_llama_backend.ps1 (URLs per backend)
REM ===========================================
:backend_check
echo  Checking LLM backend (llama-server)...
echo.

if exist "%TOOLS_DIR%\!BACKEND!\llama-server.exe" (
    echo  [OK] Backend !BACKEND! already installed.
    goto :vcredist_deploy
)

echo  Downloading llama.cpp for !BACKEND! ^(release !LLAMA_VER! — may take several minutes^)...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%App\tools\install_llama_backend.ps1" -Version "!LLAMA_VER!" -Backend "!BACKEND!" -ToolsDir "%TOOLS_DIR%" -DataDir "%DATA_DIR%"
if errorlevel 1 set "LLAMA_DL_FAIL=1"
if not exist "%TOOLS_DIR%\!BACKEND!\llama-server.exe" set "LLAMA_DL_FAIL=1"
if not defined LLAMA_DL_FAIL goto :backend_dl_ok
set "LLAMA_DL_FAIL="
REM RTX 50xx path: CUDA 13.1 zip failed or incomplete — retry with 12.4 (same GPU driver; different llama.cpp build)
if "!BACKEND!"=="nvidia-cuda-13.1" (
    echo.
    echo  [INFO] CUDA 13.1 bundle unavailable or incomplete — falling back to CUDA 12.4 for llama-server.
    set "BACKEND=nvidia-cuda-12.4"
    powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%App\tools\install_llama_backend.ps1" -Version "!LLAMA_VER!" -Backend "!BACKEND!" -ToolsDir "%TOOLS_DIR%" -DataDir "%DATA_DIR%"
    if errorlevel 1 goto :backend_manual_fallback
    if not exist "%TOOLS_DIR%\!BACKEND!\llama-server.exe" goto :backend_manual_fallback
    echo  [OK] llama-server.exe ready in %TOOLS_DIR%\!BACKEND!\
    goto :vcredist_deploy
)
goto :backend_manual_fallback

:backend_dl_ok
set "LLAMA_DL_FAIL="
echo  [OK] llama-server.exe ready in %TOOLS_DIR%\!BACKEND!\
goto :vcredist_deploy

:backend_manual_fallback
echo.
echo  [WARNING] Automatic backend install failed. Install manually into:
echo    %TOOLS_DIR%\!BACKEND!\
echo.
echo  URLs ^(tag !LLAMA_VER!^):
if "!BACKEND!"=="nvidia-cuda-12.4" (
    echo    https://github.com/ggml-org/llama.cpp/releases/download/!LLAMA_VER!/llama-!LLAMA_VER!-bin-win-cuda-12.4-x64.zip
    echo    https://github.com/ggml-org/llama.cpp/releases/download/!LLAMA_VER!/cudart-llama-bin-win-cuda-12.4-x64.zip
)
if "!BACKEND!"=="nvidia-cuda-13.1" (
    echo    https://github.com/ggml-org/llama.cpp/releases/download/!LLAMA_VER!/llama-!LLAMA_VER!-bin-win-cuda-13.1-x64.zip
    echo    https://github.com/ggml-org/llama.cpp/releases/download/!LLAMA_VER!/cudart-llama-bin-win-cuda-13.1-x64.zip
)
if "!BACKEND!"=="vulkan" (
    echo    https://github.com/ggml-org/llama.cpp/releases/download/!LLAMA_VER!/llama-!LLAMA_VER!-bin-win-vulkan-x64.zip
)
if "!BACKEND!"=="cpu" (
    echo    https://github.com/ggml-org/llama.cpp/releases/download/!LLAMA_VER!/llama-!LLAMA_VER!-bin-win-cpu-x64.zip
)
echo.
start "" "https://github.com/ggml-org/llama.cpp/releases/tag/!LLAMA_VER!"
echo  Press any key after extracting the zip(s^) here, or to continue without llama-server...
pause >nul
if not exist "%TOOLS_DIR%\!BACKEND!\llama-server.exe" (
    echo  [WARNING] Backend still missing. Run install.bat again when ready.
)

REM ===========================================
REM  STEP 7b: Deploy VC++ runtime (portable)
REM  Copies msvcp140 / vcruntime140 into:
REM  - each existing backend folder (for llama-server.exe)
REM  - Python\ (for ctranslate2.dll / faster-whisper and other C extensions)
REM ===========================================
:vcredist_deploy
echo.
echo  Deploying VC++ runtime (portable)...
if not exist "%APP_DIR%Assets\vcredist-x64-portable.zip" (
    echo  [SKIP] Assets\vcredist-x64-portable.zip not found.
    goto :final_step
)
set "VCREXT=%TEMP%\perkysue_vcredist_%RANDOM%"
mkdir "%VCREXT%" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%APP_DIR%Assets\vcredist-x64-portable.zip' -DestinationPath '%VCREXT%' -Force"
for %%b in (nvidia-cuda-12.4 nvidia-cuda-13.1 vulkan cpu) do (
    if exist "%TOOLS_DIR%\%%b\" (
        for /r "%VCREXT%" %%f in (*.dll) do copy /Y "%%f" "%TOOLS_DIR%\%%b\" >nul 2>&1
        echo  [OK] VC++ runtime deployed to %%b\
    )
)
if exist "%PYTHON_DIR%\python.exe" (
    for /r "%VCREXT%" %%f in (*.dll) do copy /Y "%%f" "%PYTHON_DIR%\" >nul 2>&1
    echo  [OK] VC++ runtime deployed to Python\
)
rmdir /s /q "%VCREXT%" 2>nul

REM ===========================================
REM  STEP 7c: Desktop shortcut
REM ===========================================
echo.
echo  Creating desktop shortcut...
set "PERKYSUE_APP_DIR=%APP_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $app = $env:PERKYSUE_APP_DIR.TrimEnd('\'); $desk = [Environment]::GetFolderPath('Desktop'); $sh = New-Object -ComObject WScript.Shell; $lnk = Join-Path $desk 'PerkySue.lnk'; $sc = $sh.CreateShortcut($lnk); $sc.TargetPath = (Join-Path $app 'PerkySue Launch.bat'); $sc.WorkingDirectory = $app; $sc.Description = 'PerkySue'; $ico = Join-Path $app 'PerkySue.ico'; if (Test-Path -LiteralPath $ico) { $sc.IconLocation = $ico }; $sc.Save(); Write-Host ('  [OK] ' + $lnk) } catch { Write-Host ('  [WARNING] Shortcut: ' + $_.Exception.Message) }"
set "PERKYSUE_APP_DIR="
goto :final_step

REM ===========================================
REM  STEP 8: Final instructions
REM ===========================================
:final_step
echo.
echo  =============================================
echo   Installation Complete!
echo  =============================================
echo.
echo  Hardware detected: !GPU_NAME!
echo  Backend: !BACKEND!
if not defined STT_ACCEL set "STT_ACCEL=CPU"
echo  STT acceleration: !STT_ACCEL!
echo.
echo  Next steps:
echo    1. Download an LLM:  Settings -^> Recommended Models (or place a .gguf in Data\Models\LLM\)
echo    2. Launch PerkySue:         start.bat
echo.
echo  Launching PerkySue...
call "%~dp0start.bat"
echo.
pause
