@echo off
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
REM ============================================================
REM  PerkySue - Launcher v2.4
REM  Detects GPU (RTX 50xx vs 40xx/30xx), activates correct CUDA backend
REM ============================================================
setlocal enabledelayedexpansion

set "APP_DIR=%~dp0"
set "PYTHON_EXE=%APP_DIR%Python\python.exe"
set "DATA_DIR=%APP_DIR%Data"
set "TOOLS_DIR=%DATA_DIR%\Tools"
set "ACTIVE_DIR=%TOOLS_DIR%\active"

REM llama.cpp release version (for error messages only)
set "LLAMA_VER=b8188"

REM Cleanup orphaned processes from previous sessions
taskkill /F /IM llama-server.exe >nul 2>&1

REM ============================================================
REM  HARDWARE DETECTION - NVIDIA with CUDA version split
REM ============================================================
echo.
echo  =============================================
echo   PerkySue - Hardware Diagnostics
echo  =============================================
echo.

set "DETECTED_BACKEND=cpu"
set "GPU_NAME=No dedicated GPU"

REM --- Check for NVIDIA ---
where nvidia-smi >nul 2>&1
if !errorlevel! neq 0 goto :check_amd_intel

REM nvidia-smi exists = NVIDIA hardware confirmed
REM Parse GPU name to detect architecture
for /f "tokens=1,* delims=:" %%a in ('nvidia-smi -L 2^>nul') do (
    set "_LINE=%%b"
)
if defined _LINE (
    set "_LINE=!_LINE:~1!"
    for /f "tokens=1 delims=(" %%g in ("!_LINE!") do set "GPU_NAME=%%g"
    if "!GPU_NAME:~-1!"==" " set "GPU_NAME=!GPU_NAME:~0,-1!"
)

REM Detect RTX 50xx (Blackwell) - CUDA 12.4 (compatible with all driver versions)
echo !GPU_NAME! | findstr /I "RTX 50 RTX50 5060 5070 5080 5090" >nul
if !errorlevel! equ 0 (
    set "DETECTED_BACKEND=nvidia-cuda-12.4"
    echo  [GPU] NVIDIA RTX 50xx detected: !GPU_NAME!
    echo  [GPU] Using CUDA 12.4 backend
    goto :detection_done
)

REM Detect RTX 40xx/30xx/20xx - CUDA 12.4
echo !GPU_NAME! | findstr /I "RTX 40 RTX40 4070 4080 4090 RTX 30 RTX30 3060 3070 3080 3090 RTX 20 RTX20 2060 2070 2080" >nul
if !errorlevel! equ 0 (
    set "DETECTED_BACKEND=nvidia-cuda-12.4"
    echo  [GPU] NVIDIA RTX 40xx/30xx/20xx detected: !GPU_NAME!
    echo  [GPU] Using CUDA 12.4 backend
    goto :detection_done
)

REM Other NVIDIA (GTX, older) - try CUDA 12.4 as fallback
set "DETECTED_BACKEND=nvidia-cuda-12.4"
echo  [GPU] NVIDIA GPU detected: !GPU_NAME!
echo  [GPU] Using CUDA 12.4 backend (fallback)
goto :detection_done

REM --- Check for AMD/Intel ---
:check_amd_intel
reg query "HKLM\SYSTEM\CurrentControlSet\Control\Video" /s /f "AMD" >nul 2>&1
if !errorlevel! equ 0 (
    set "GPU_NAME=AMD GPU"
    set "DETECTED_BACKEND=vulkan"
    echo  [GPU] AMD detected - Vulkan backend
    goto :detection_done
)

reg query "HKLM\SYSTEM\CurrentControlSet\Control\Video" /s /f "Intel" >nul 2>&1
if !errorlevel! equ 0 (
    set "GPU_NAME=Intel GPU"
    set "DETECTED_BACKEND=vulkan"
    echo  [GPU] Intel detected - Vulkan backend
    goto :detection_done
)

REM --- CPU fallback ---
echo  [GPU] No dedicated GPU - CPU backend
set "DETECTED_BACKEND=cpu"

:detection_done
echo.
echo  [DEBUG] ========== DETECTION RESULT ==========
echo  [DEBUG] GPU Name: !GPU_NAME!
echo  [DEBUG] Backend: !DETECTED_BACKEND!
echo  [DEBUG] ======================================
echo.

REM ============================================================
REM  BACKEND VERIFICATION
REM ============================================================
if exist "%TOOLS_DIR%\!DETECTED_BACKEND!\llama-server.exe" goto :backend_ok

echo.
echo  [ERROR] Backend not found:
echo     %TOOLS_DIR%\!DETECTED_BACKEND!
echo.
echo  This Patreon tier should include all backends.
echo  If you're a GitHub user, run install.bat first.
echo.
echo  Manual download: https://github.com/ggml-org/llama.cpp/releases/tag/!LLAMA_VER!
pause
exit /b 1

:backend_ok
echo  [OK] Backend found: !DETECTED_BACKEND!


REM Test if backend can actually execute (antivirus check)
echo  Testing backend execution...
pushd "%TOOLS_DIR%\!DETECTED_BACKEND!"
llama-server.exe --version >nul 2>&1
if errorlevel 1 (
    popd
    echo.
    echo  =============================================
    echo   WARNING: Antivirus blocked llama-server.exe
    echo  =============================================
    echo.
    echo  Windows Defender or your antivirus prevented
    echo  the LLM server from running.
    echo.
    echo  SOLUTION: Add this folder to exclusions:
    echo     %TOOLS_DIR%\!DETECTED_BACKEND!
    echo.
    echo  Steps:
    echo  1. Windows Settings - Security - Virus protection
    echo  2. Manage settings - Exclusions - Add folder
    echo  3. Paste this path:
    echo     %TOOLS_DIR%\!DETECTED_BACKEND!
    echo.
    pause
    exit /b 1
)
popd

REM ============================================================
REM  BACKEND ACTIVATION
REM ============================================================
echo  Activating backend...

if exist "%ACTIVE_DIR%" rmdir /S /Q "%ACTIVE_DIR%" 2>nul
mkdir "%ACTIVE_DIR%" 2>nul

xcopy /Y /E /Q "%TOOLS_DIR%\!DETECTED_BACKEND!\*" "%ACTIVE_DIR%\" >nul 2>&1

if not exist "%ACTIVE_DIR%\llama-server.exe" (
    echo  [ERROR] Backend activation failed!
    pause
    exit /b 1
)

echo  [OK] Backend activated.

REM ============================================================
REM  ENVIRONMENT SETUP
REM ============================================================
set "HF_HOME=%DATA_DIR%\HuggingFace"
set "HF_HUB_CACHE=%DATA_DIR%\HuggingFace\hub"
set "HUGGINGFACE_HUB_CACHE=%DATA_DIR%\HuggingFace\hub"
set "TRANSFORMERS_CACHE=%DATA_DIR%\HuggingFace"
set "XDG_CACHE_HOME=%DATA_DIR%\Cache"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "PERKYSUE_DATA=%DATA_DIR%"

REM ------------------------------------------------------------------
REM  Optional - alternate base URL for remote entitlement HTTP only.
REM  Value must be an HTTPS origin (no path), e.g. https://xxx.workers.dev
REM  Uncomment and set locally for internal builds; do not commit real URLs.
REM  Name is obscure on purpose; see private handoff if you need this.
REM ------------------------------------------------------------------
REM set PERKYSUE_LICENSE_API=

if not exist "%PYTHON_EXE%" (
    echo  [ERROR] Python not found! Run install.bat first.
    pause
    exit /b 1
)

REM ============================================================
REM  PYTHON DEPENDENCIES CHECK
REM ============================================================
echo  Checking Python dependencies...

"%PYTHON_EXE%" -c "import yaml, numpy, requests, pygame, faster_whisper, psutil" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [WARNING] Missing Python modules detected!
    echo  Installing: pyyaml, numpy, requests, pygame, faster-whisper, psutil...
    echo.
    
    "%PYTHON_EXE%" -m pip install pyyaml numpy requests pygame faster-whisper psutil --quiet
    
    if errorlevel 1 (
        echo  [ERROR] Failed to install dependencies.
        echo  Please run: install.bat
        pause
        exit /b 1
    )
    
    echo  [OK] Dependencies installed.
) else (
    echo  [OK] All dependencies ready.
)

REM ============================================================
REM  LAUNCH SEQUENCE
REM ============================================================
echo.
echo  =============================================
echo   Launching PerkySue
echo  =============================================
echo.

REM Server is now managed by Python - no need to pre-launch here.
REM Pass detected backend info to Python via environment variable
set "PERKYSUE_BACKEND=!DETECTED_BACKEND!"
set "PERKYSUE_GPU_NAME=!GPU_NAME!"

REM ============================================================
REM  DEFAULT WHISPER MODEL (first run)
REM  CPU/Vulkan machines should default to Whisper Small (faster/lower RAM).
REM  Only apply when user config does not exist yet.
REM ============================================================
if /I "!DETECTED_BACKEND!"=="cpu" goto :maybe_seed_small
if /I "!DETECTED_BACKEND!"=="vulkan" goto :maybe_seed_small
goto :seed_done

:maybe_seed_small
if exist "%DATA_DIR%\Configs\config.yaml" goto :seed_done
if not exist "%DATA_DIR%\Configs" mkdir "%DATA_DIR%\Configs" 2>nul
echo  [INFO] First run on !DETECTED_BACKEND! - seeding default STT model: Whisper Small
(
  echo stt:
  echo   model: "small"
) > "%DATA_DIR%\Configs\config.yaml"

:seed_done

echo  Starting PerkySue...
"%PYTHON_EXE%" "%APP_DIR%App\main.py"

echo.
echo  PerkySue has stopped. (exit code: %errorlevel%)
pause