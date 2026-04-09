@echo off
setlocal
cd /d "%~dp0"
title PerkySue - PyTorch CUDA 12.8 for TTS (Blackwell / RTX 50xx)
echo.
echo  For NVIDIA RTX 50xx (sm_120): PyTorch cu124 wheels do NOT include your GPU.
echo  This uses official cu128 wheels (PyTorch 2.7+). Close PerkySue first.
echo  Older GPUs: use install_pytorch_cuda_cu124.bat instead.
echo.
"%~dp0Python\python.exe" -m pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
echo.
pause
