# Exit 0 if nvidia-smi reports CUDA Version >= 13.0 (driver capability for CUDA 13.x user-mode).
# Exit 1 otherwise (use llama.cpp CUDA 12.4 zips). Does not require CUDA Toolkit / nvcc on PATH.
$ErrorActionPreference = 'Stop'
try {
    $raw = (nvidia-smi 2>&1 | Out-String)
    if ($raw -match 'CUDA Version:\s*(\d+)\.(\d+)') {
        $maj = [int]$Matches[1]
        if ($maj -ge 13) { exit 0 }
    }
}
catch { }
exit 1
