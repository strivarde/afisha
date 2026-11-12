@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo Ищу новые Telegram-каналы с анонсами (5-15 минут)...
.venv\Scripts\python discover.py --venues --limit=80
start "" "output\sources.html"
pause
