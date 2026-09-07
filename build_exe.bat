@echo off
REM TurboCore - build do executavel (duplo clique ou: build_exe.bat)
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt || exit /b 1
python assets\generate_icon.py || exit /b 1
set PYTHONPATH=src
python -m pytest tests\ -q || exit /b 1
taskkill /f /im TurboCore.exe 2>nul
python -m PyInstaller --noconfirm --clean --name TurboCore --windowed --icon assets\chip.ico --paths src --add-data "assets\chip.ico;assets" src\turbocore\main.py || exit /b 1
echo OK: dist\TurboCore\TurboCore.exe
