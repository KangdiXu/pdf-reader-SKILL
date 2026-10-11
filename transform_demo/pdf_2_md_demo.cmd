@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%"
if errorlevel 1 (
    echo [错误] 无法进入演示目录："%SCRIPT_DIR%"
    exit /b 1
)

echo 当前工作目录："%CD%"
conda run --no-capture-output -n pdf_read python -u "..\scripts\extract_pdf.py" transfer "%SCRIPT_DIR%test_pdf_read_script.pdf"
set "DEMO_STATUS=%ERRORLEVEL%"
if not "%DEMO_STATUS%"=="0" echo [错误] PDF 转换失败，退出码：%DEMO_STATUS%
echo.
pause
popd
exit /b %DEMO_STATUS%
