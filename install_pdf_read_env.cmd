@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem ============================================================
rem pdf-reader skill Windows 环境安装脚本
rem 1. 检查 conda 是否已安装
rem 2. 检查 pdf_read 环境是否存在，不存在则创建
rem 3. 安装 Windows 可用的第三方依赖
rem 4. 选择目标 AI agent，安装 skill 到对应目录
rem ============================================================

chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
set "ENV_NAME=pdf_read"
set "SKILL_NAME=pdf-reader"
set "REQUIREMENTS_FILE=%SCRIPT_DIR%pdf_read_env_requirements.txt"
set "YML_FILE=%SCRIPT_DIR%pdf_read_env.yml"
set "TEMP_REQUIREMENTS_FILE="

echo ==========================================
echo   pdf-reader skill Windows 环境安装
echo ==========================================

rem ---- 检查安装文件 ----
if not exist "%YML_FILE%" (
    echo [错误] 未找到环境配置文件：%YML_FILE%
    goto :failed
)
if not exist "%REQUIREMENTS_FILE%" (
    echo [错误] 未找到依赖清单：%REQUIREMENTS_FILE%
    goto :failed
)
if not exist "%SCRIPT_DIR%pdf_2_md_main.py" (
    echo [错误] 未找到核心脚本：%SCRIPT_DIR%pdf_2_md_main.py
    goto :failed
)
if not exist "%SCRIPT_DIR%SKILL.md" (
    echo [错误] 未找到 skill 说明文件：%SCRIPT_DIR%SKILL.md
    goto :failed
)

rem ---- 1. 检查 conda ----
echo.
echo [1/4] 检查 conda...

where conda >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 conda。
    echo        请先安装 Miniconda 或 Anaconda：
    echo        https://docs.conda.io/projects/miniconda/en/latest/
    goto :failed
)

set "CONDA_BASE="
for /f "delims=" %%I in ('call conda info --base 2^>nul') do set "CONDA_BASE=%%I"
if not defined CONDA_BASE (
    echo [错误] conda 可执行，但无法读取 base 环境路径。
    goto :failed
)
echo [完成] conda 已安装 ^(base: %CONDA_BASE%^)

rem ---- 2. 检查/创建 pdf_read 环境 ----
echo.
echo [2/4] 检查 conda 环境 "%ENV_NAME%"...

set "ENV_EXISTS="
for /f "tokens=1" %%E in ('call conda env list 2^>nul') do call :mark_env_if_match "%%E"

if defined ENV_EXISTS goto :env_ready

echo [提示] 环境 "%ENV_NAME%" 不存在，正在从 pdf_read_env.yml 创建...
rem 显式按环境名创建，由当前设备的 conda 自行决定环境安装目录。
call conda env create --name "%ENV_NAME%" --file "%YML_FILE%" -y
if errorlevel 1 (
    echo [错误] 创建 conda 环境 "%ENV_NAME%" 失败。
    goto :failed
)
echo [完成] 环境 "%ENV_NAME%" 创建完成。
goto :install_dependencies

:env_ready
echo [完成] 环境 "%ENV_NAME%" 已存在，跳过创建。

:install_dependencies
rem ---- 3. 安装 Windows 可用的第三方库 ----
echo.
echo [3/4] 检查并安装第三方依赖...

:make_temp_name
set "TEMP_REQUIREMENTS_FILE=%TEMP%\pdf-reader-requirements-%RANDOM%-%RANDOM%.txt"
if exist "%TEMP_REQUIREMENTS_FILE%" goto :make_temp_name

rem 以下包只用于 macOS/POSIX；核心转换程序在 Windows 上不需要它们。
findstr /V /B /I /C:"appnope==" /C:"pexpect==" /C:"ptyprocess==" "%REQUIREMENTS_FILE%" > "%TEMP_REQUIREMENTS_FILE%"
if errorlevel 1 (
    echo [错误] 无法生成 Windows 依赖清单。
    goto :failed
)

echo [提示] pip 会保留已满足的依赖，仅安装缺失或版本不匹配的依赖。
echo [提示] Windows 上已跳过 appnope、pexpect 和 ptyprocess。
call conda run --no-capture-output -n "%ENV_NAME%" python -m pip install --requirement "%TEMP_REQUIREMENTS_FILE%"
if errorlevel 1 (
    echo [错误] 安装第三方依赖失败。
    goto :failed
)

del /Q "%TEMP_REQUIREMENTS_FILE%" >nul 2>&1
set "TEMP_REQUIREMENTS_FILE="

call conda run -n "%ENV_NAME%" python -c "import pymupdf4llm, pathlib"
if errorlevel 1 (
    echo [错误] 核心依赖导入验证失败。
    goto :failed
)
echo [完成] 所有 Windows 依赖均已就绪。

rem ---- 4. 选择 agent 并安装 skill ----
echo.
echo [4/4] 安装 skill 到 AI agent...
echo.
echo   请选择要安装到哪款 AI agent：
echo     [1] Codex
echo     [2] Claude
echo.
choice /C 12 /N /M "  请输入 1 或 2："
if errorlevel 2 goto :select_claude

:select_codex
set "AGENT_NAME=Codex"
set "AGENT_DIR=%USERPROFILE%\.codex"
set "AGENT_SKILLS_SUBDIR=skills"
goto :agent_selected

:select_claude
set "AGENT_NAME=Claude"
set "AGENT_DIR=%USERPROFILE%\.claude"
set "AGENT_SKILLS_SUBDIR=skills"

:agent_selected
echo.
echo   已选择：%AGENT_NAME%
echo.

if not exist "%AGENT_DIR%\" (
    echo [错误] 未找到 %AGENT_DIR%
    echo        可能没有安装 %AGENT_NAME% 或尚未完成初始配置。
    goto :failed
)

set "SKILLS_DIR=%AGENT_DIR%\%AGENT_SKILLS_SUBDIR%"
if not exist "%SKILLS_DIR%\" (
    echo [提示] 未找到 %SKILLS_DIR%，正在创建...
    mkdir "%SKILLS_DIR%"
    if errorlevel 1 (
        echo [错误] 无法创建 skills 目录：%SKILLS_DIR%
        goto :failed
    )
    echo [完成] 已创建 %SKILLS_DIR%
)

set "SKILL_TARGET=%SKILLS_DIR%\%SKILL_NAME%"

if exist "%SKILL_TARGET%\" goto :confirm_overwrite

echo.
echo   安装路径：%SKILL_TARGET%
choice /C YN /N /M "  确定要安装吗？[Y/N] "
if errorlevel 2 goto :cancelled
goto :install_skill

:confirm_overwrite
echo.
echo [提示] %AGENT_NAME% 已安装 %SKILL_NAME% skill：%SKILL_TARGET%
choice /C YN /N /M "  是否覆盖？[Y/N] "
if errorlevel 2 goto :cancelled

rmdir /S /Q "%SKILL_TARGET%"
if exist "%SKILL_TARGET%\" (
    echo [错误] 无法移除原有 skill 目录：%SKILL_TARGET%
    goto :failed
)

:install_skill
mkdir "%SKILL_TARGET%"
if errorlevel 1 (
    echo [错误] 无法创建 skill 目录：%SKILL_TARGET%
    goto :failed
)

copy /Y "%SCRIPT_DIR%pdf_2_md_main.py" "%SKILL_TARGET%\pdf_2_md_main.py" >nul
if errorlevel 1 goto :copy_failed
copy /Y "%SCRIPT_DIR%SKILL.md" "%SKILL_TARGET%\SKILL.md" >nul
if errorlevel 1 goto :copy_failed

set "PY_SCRIPT_PATH=%SKILL_TARGET%\pdf_2_md_main.py"
call conda run -n "%ENV_NAME%" python -c "from pathlib import Path; import sys; p=Path(sys.argv[1]); s=p.read_text(encoding='utf-8'); marker='### 0. 环境准备'; insert=marker+'\n\n**0a. skill 核心python脚本的路径**\nAGENT_SKILL_py_PATH='+sys.argv[2]; assert marker in s, 'SKILL.md 中缺少环境准备标记'; p.write_text(s.replace(marker, insert, 1), encoding='utf-8')" "%SKILL_TARGET%\SKILL.md" "%PY_SCRIPT_PATH%"
if errorlevel 1 (
    echo [错误] 无法将核心 Python 脚本路径写入 SKILL.md。
    goto :failed
)

echo.
echo ==========================================
echo   [完成] pdf_read 环境准备就绪！
echo   [完成] %SKILL_NAME% skill 已安装到 %AGENT_NAME%
echo          路径：%SKILL_TARGET%
echo ==========================================
exit /b 0

:mark_env_if_match
if /I "%~1"=="%ENV_NAME%" set "ENV_EXISTS=1"
exit /b 0

:copy_failed
echo [错误] 复制 skill 文件失败。
goto :failed

:cancelled
echo [取消] 已取消安装。
exit /b 0

:failed
if defined TEMP_REQUIREMENTS_FILE if exist "%TEMP_REQUIREMENTS_FILE%" del /Q "%TEMP_REQUIREMENTS_FILE%" >nul 2>&1
echo.
echo 安装未完成。
exit /b 1
