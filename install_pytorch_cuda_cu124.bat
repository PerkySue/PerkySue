@echo off
setlocal
cd /d "%~dp0"
title PerkySue - PyTorch CUDA 12.4 for TTS
echo.
echo  Replaces CPU-only PyTorch with CUDA 12.4 wheels (RTX 40xx and older; sm_50–sm_90).
echo  RTX 50xx / Blackwell: use install_pytorch_cuda_cu128.bat — cu124 cannot run on sm_120.
echo  Close PerkySue before running. Whisper and llama-server are unchanged.
echo.
"%~dp0Python\python.exe" -m pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
echo.
pause
