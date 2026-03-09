
@echo off
:: Navigate to the project directory
:: Replace the path below with the actual path on your Windows machine
cd /d "C:\Users\innovapathinc\Desktop\wbl\project-outreach-mass-email"

:: Activate the virtual environment and run the script
call venv\Scripts\activate
python run_once.py

:: Optional: Keep window open if there is an error
if %errorlevel% neq 0 pause
