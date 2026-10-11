@echo off
echo ==============================================
echo   Збірка клієнта для ПК клубу в EXE
echo ==============================================

pip install -r requirements.txt

echo.
echo Компіляція за допомогою PyInstaller...
rem --collect-submodules pyautogui: без цього pyautogui часто не потрапляє у збірку,
rem і керування мишею на ПК клубу мовчки не працює (виручає лише Win32-бекенд).
pyinstaller --onefile --noconsole --name "pc_client" ^
  --collect-submodules pyautogui ^
  --hidden-import pyautogui ^
  --hidden-import pyscreeze ^
  --hidden-import pymsgbox ^
  --hidden-import pytweening ^
  --hidden-import mouseinfo ^
  --hidden-import pygetwindow ^
  --hidden-import pyperclip ^
  client.py

echo.
echo ==============================================
echo Збірка завершена!
echo Файл pc_client.exe знаходиться в папці dist\
echo Скопіюйте pc_client.exe та client_config.json на ПК клубу.
echo ==============================================
pause
