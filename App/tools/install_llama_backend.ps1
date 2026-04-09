# PerkySue — download and extract llama.cpp Windows binaries (llama-server) for install.bat
# Base URL: https://github.com/ggml-org/llama.cpp/releases/download/<tag>/
# Per backend: CUDA 12.4/13.1 (main + cudart), Vulkan (1 zip), CPU (1 zip).
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Backend,
    [Parameter(Mandatory = $true)][string]$ToolsDir,
    [Parameter(Mandatory = $true)][string]$DataDir
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

try {

$base = "https://github.com/ggml-org/llama.cpp/releases/download/$Version"
$be = Join-Path $ToolsDir $Backend
$cache = Join-Path $DataDir "Cache\llama-backend"
New-Item -ItemType Directory -Force -Path $be, $cache | Out-Null

$urls = switch ($Backend) {
    'nvidia-cuda-12.4' {
        @(
            "$base/llama-$Version-bin-win-cuda-12.4-x64.zip",
            "$base/cudart-llama-bin-win-cuda-12.4-x64.zip"
        )
    }
    'nvidia-cuda-13.1' {
        @(
            "$base/llama-$Version-bin-win-cuda-13.1-x64.zip",
            "$base/cudart-llama-bin-win-cuda-13.1-x64.zip"
        )
    }
    'vulkan' { @("$base/llama-$Version-bin-win-vulkan-x64.zip") }
    'cpu' { @("$base/llama-$Version-bin-win-cpu-x64.zip") }
    default { throw "Unknown backend: $Backend" }
}

function Expand-ZipInto {
    param([string]$ZipPath, [string]$DestDir)
    $tmp = Join-Path $env:TEMP ("perkysue_llama_" + [guid]::NewGuid().ToString('n'))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        Expand-Archive -LiteralPath $ZipPath -DestinationPath $tmp -Force
        $top = @(Get-ChildItem -LiteralPath $tmp -Force)
        if ($top.Count -eq 1 -and $top[0].PSIsContainer) {
            Copy-Item -Path (Join-Path $top[0].FullName '*') -Destination $DestDir -Recurse -Force
        }
        else {
            Copy-Item -Path (Join-Path $tmp '*') -Destination $DestDir -Recurse -Force
        }
    }
    finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

foreach ($url in $urls) {
    $name = Split-Path $url -Leaf
    $zipPath = Join-Path $cache $name
    if (-not (Test-Path -LiteralPath $zipPath)) {
        Write-Host "Downloading $name ..."
        Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
    }
    else {
        Write-Host "Using cached $name"
    }
    Expand-ZipInto -ZipPath $zipPath -DestDir $be
}

$exe = Join-Path $be 'llama-server.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    throw "llama-server.exe not found under $be"
}
Write-Host "OK: $exe"

}
catch {
    Write-Host ("ERROR: " + $_.Exception.Message)
    exit 1
}
exit 0
