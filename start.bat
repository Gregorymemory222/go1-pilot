@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
    echo Pierwsze uruchomienie - tworze srodowisko Pythona...
    py -3 -m venv .venv || goto :error
)
.venv\Scripts\python.exe -c "import paho.mqtt, vosk, sounddevice" 2>nul || (
    echo Instaluje biblioteki...
    .venv\Scripts\python.exe -m pip install -q -r requirements.txt || goto :error
)
if not exist models\vosk-model-small-pl-0.22 (
    echo Pobieram polski model mowy, ok. 50 MB - potrzebny internet...
    .venv\Scripts\python.exe -c "from voice import ensure_model; ensure_model(print)" || goto :error
)
start "" .venv\Scripts\pythonw.exe server.py
exit /b 0

:error
echo Nie udalo sie przygotowac programu. Sprawdz internet i sprobuj ponownie.
pause
