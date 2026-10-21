@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
    echo Pierwsze uruchomienie - instaluje biblioteki...
    py -3 -m venv .venv || goto :error
    .venv\Scripts\python.exe -m pip install -q -r requirements.txt || goto :error
)
start "" .venv\Scripts\pythonw.exe app.py
exit /b 0

:error
echo Nie udalo sie przygotowac srodowiska Pythona.
pause
