@echo off
cd /d "%~dp0"
echo 受注管理システムを起動中...
pip install -r requirements.txt --quiet
python app.py
pause
