@echo off
echo ==============================================
echo   Збірка клієнта для ПК клубу в EXE
echo ==============================================

pip install -r requirements.txt

echo.
echo Компіляція за допомогою PyInstaller...
pyinstaller --onefile --noconsole --name "pc_client" client.py

echo.
echo ==============================================
echo Збірка завершена!
echo Файл pc_client.exe знаходиться в папці dist\
echo Скопіюйте pc_client.exe та client_config.json на ПК клубу.
echo ==============================================
pause
