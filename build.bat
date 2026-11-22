@echo off
setlocal
cd /d "%~dp0"

set "APP_NAME=Mine BookWalker DownLoader"
set "PYTHON_EXE=python"

if exist "dist" rmdir /s /q "dist"

if exist "build" rmdir /s /q "build"
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean --windowed --onefile --name "%APP_NAME%" --icon "qss\icons\icon.ico" --paths "." --add-data "qss;qss" --add-data "ui\tabs\web_script\js;ui\tabs\web_script\js" --add-binary "C\*.pyd;C" --hidden-import "path_clean" --hidden-import "C.c_margins" --hidden-import "C.c_header" --hidden-import "C.c_layout" --hidden-import "C.c_illust" --collect-submodules "google.genai" "main.py"
if errorlevel 1 goto :fail

if exist "build" rmdir /s /q "build"
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

echo.
echo Build completed:
echo   dist\%APP_NAME%.exe
exit /b 0

:fail
echo.
echo Build failed.
exit /b 1
