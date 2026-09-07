#!/bin/bash
# Build TurboCore.exe (log em arquivo, exit code preservado)
cd D:/Projetos/TurboCore || exit 1
export PYTHONPATH=D:/Projetos/TurboCore/src
python assets/generate_icon.py > /tmp/tc_build.log 2>&1 || { echo "ICON_FAIL"; exit 1; }
python -m pytest tests/ -q >> /tmp/tc_build.log 2>&1 || { echo "TESTS_FAIL"; tail -n 5 /tmp/tc_build.log; exit 1; }
taskkill //F //IM TurboCore.exe > /dev/null 2>&1
powershell.exe -NoProfile -Command "Stop-Process -Name TurboCore -Force -ErrorAction SilentlyContinue" > /dev/null 2>&1
sleep 2
python -m PyInstaller --noconfirm --clean --name TurboCore --windowed --icon assets/chip.ico --paths src --add-data "assets/chip.ico;assets" src/turbocore/main.py >> /tmp/tc_build.log 2>&1
status=$?
tail -n 6 /tmp/tc_build.log
echo "BUILD_EXIT=$status"
ls -la dist/TurboCore/TurboCore.exe 2>&1
exit $status
