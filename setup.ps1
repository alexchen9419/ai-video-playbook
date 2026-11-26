# Windows 安裝：在 repo 根目錄執行  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "找不到 python，請先安裝 Python 3.10 以上（winget install Python.Python.3.11）" }
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m playwright install chromium
& .\.venv\Scripts\python.exe check_env.py
Write-Host "`n完成。之後先執行 .\.venv\Scripts\Activate.ps1 再跑 工具/ 裡的腳本。"
