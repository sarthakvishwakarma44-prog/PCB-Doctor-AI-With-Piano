@echo off
pip install -r requirements.txt
set /p GEMINI_API_KEY=Enter your Gemini API Key: 
python bt_watcher.py
pause
