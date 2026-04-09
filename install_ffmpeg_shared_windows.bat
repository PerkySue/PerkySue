@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo.
echo ===============================================================================
echo  PerkySue — FFmpeg DLLs for TorchCodec / OmniVoice (Windows, portable)
echo ===============================================================================
echo.
echo TorchAudio 2.9+ uses TorchCodec, which loads native FFmpeg DLLs.
echo  "pip install ffmpeg-python" does NOT provide those DLLs.
echo.
echo Recommended: BtbN shared build (includes avcodec-, avutil-, etc. in bin\)
echo   https://github.com/BtbN/FFmpeg-Builds/releases
echo   File example: ffmpeg-master-latest-win64-gpl-shared.zip
echo.
echo Steps:
echo   1. Download and extract the ZIP.
echo   2. Open the "bin" folder inside the extracted tree.
echo   3. Copy ALL files from that bin folder into ONE of:
echo        - Python\     (next to python.exe)  ^<^< default, simple
echo        - Data\Tools\ffmpeg-shared\bin\     ^<^< keeps Python folder clean
echo.
echo PerkySue registers these folders automatically at OmniVoice startup.
echo Chatterbox does not need this; only use this if you rely on TorchCodec paths.
echo.
echo ===============================================================================
pause
