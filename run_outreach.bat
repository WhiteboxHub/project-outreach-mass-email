
@echo off
:: Navigate to the project directory (uses current script directory dynamically)
cd /d "%~dp0"

:: Set UTF-8 console and Python I/O encoding
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

:: Activate the virtual environment and run the script
call venv\Scripts\activate
python run_once.py

:: Optional: Keep window open if there is an error
if %errorlevel% neq 0 pause
