$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt
python -m pip install "pyinstaller>=6.0"
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "HinanaVoice" `
    --collect-all sounddevice `
    --collect-all soundfile `
    .\hinana_app.py

if ($LASTEXITCODE -ne 0) {
    throw "HinanaVoice.exe 빌드에 실패했습니다. 실행 중인 기존 프로그램을 닫고 다시 시도하세요."
}

Write-Host "완료: $PSScriptRoot\dist\HinanaVoice.exe"
