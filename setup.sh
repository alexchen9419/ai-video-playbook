#!/usr/bin/env bash
# macOS / Linux 安裝：bash setup.sh
set -e
command -v python3 >/dev/null || { echo "找不到 python3，請先安裝 Python 3.10 以上"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m playwright install chromium
./.venv/bin/python check_env.py
echo; echo "完成。之後先執行 source .venv/bin/activate 再跑 工具/ 裡的腳本。"
