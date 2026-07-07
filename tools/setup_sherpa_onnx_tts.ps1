param(
    [string]$ProjectRoot = "C:\Users\Wang Zailiang\Desktop\Camera_Agent_latest-main",
    [string]$DataRoot = "D:\camera_agent_data",
    [string]$ModelUrl = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-vits-zh-ll.tar.bz2"
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

$modelRoot = Join-Path $DataRoot "local_models\sherpa_onnx_tts"
$modelDir = Join-Path $modelRoot "sherpa-onnx-vits-zh-ll"
$archivePath = Join-Path $modelRoot "sherpa-onnx-vits-zh-ll.tar.bz2"
$venvDir = Join-Path $DataRoot "venvs\sherpa-onnx-tts"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirements = Join-Path $ProjectRoot "requirements_sherpa_onnx_tts.txt"

New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "venvs") | Out-Null

if (-not (Test-Path $venvPython)) {
    & "D:\Anaconda\python.exe" -m venv $venvDir
}

Invoke-Checked $venvPython @("-m", "pip", "install", "--upgrade", "pip")
if (Test-Path $requirements) {
    Invoke-Checked $venvPython @("-m", "pip", "install", "-r", $requirements)
} else {
    Invoke-Checked $venvPython @("-m", "pip", "install", "numpy", "sherpa-onnx")
}

if (-not (Test-Path $modelDir)) {
    if (-not (Test-Path $archivePath)) {
        Invoke-WebRequest -Uri $ModelUrl -OutFile $archivePath -UseBasicParsing
    }
    Invoke-Checked "tar" @("-xjf", $archivePath, "-C", $modelRoot)
}

Write-Host "sherpa-onnx TTS environment is ready."
Write-Host "Model: $modelDir"
Write-Host "Python: $venvPython"
