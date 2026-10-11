@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem pdf-reader skill installer for Windows x64.
rem Existing environments are reused only after Python/platform validation.
rem Skill replacement is staged and rolled back if activation fails.

chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
set "ENV_NAME=pdf_read"
set "SKILL_NAME=pdf-reader"
set "REQUIREMENTS_FILE=%SCRIPT_DIR%pdf_read_env_requirements.txt"
set "YML_FILE=%SCRIPT_DIR%pdf_read_env.yml"
set "EXTRACTOR_FILE=%SCRIPT_DIR%scripts\extract_pdf.py"
set "TEMP_ENV_JSON=%TEMP%\pdf-reader-envs-%RANDOM%-%RANDOM%.json"
set "TEMP_INFO_JSON=%TEMP%\pdf-reader-info-%RANDOM%-%RANDOM%.json"
set "STAGE_DIR="
set "BACKUP_DIR="

echo ==========================================
echo   pdf-reader skill Windows x64 安装
echo ==========================================

rem ---- 完整预检 ----
if not exist "%YML_FILE%" goto :missing_yml
if not exist "%REQUIREMENTS_FILE%" goto :missing_requirements
if not exist "%SCRIPT_DIR%SKILL.md" goto :missing_skill
if not exist "%SCRIPT_DIR%README.md" goto :missing_readme
if not exist "%SCRIPT_DIR%pdf_2_md_main.py" goto :missing_wrapper
if not exist "%EXTRACTOR_FILE%" goto :missing_extractor
if not exist "%SCRIPT_DIR%references\ocr.md" goto :missing_ocr_guide

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
set "CONDA_EXE=%CONDA_BASE%\Scripts\conda.exe"
if not exist "%CONDA_EXE%" (
    echo [错误] 未找到 conda.exe："%CONDA_EXE%"
    goto :failed
)
echo [完成] conda 已安装 ^(base: "%CONDA_BASE%"^)

"%CONDA_EXE%" info --json > "%TEMP_INFO_JSON%"
if errorlevel 1 (
    echo [错误] conda info 查询失败。
    goto :failed
)
powershell -NoProfile -Command "try { $v = Get-Content -LiteralPath $env:TEMP_INFO_JSON -Raw -Encoding UTF8 | ConvertFrom-Json; if ($v.platform -eq 'win-64') { exit 0 }; Write-Host ('[错误] 当前 conda platform 为 ' + $v.platform + '，固定依赖仅支持 win-64。'); exit 1 } catch { Write-Host ('[错误] 无法解析 conda info JSON：' + $_.Exception.Message); exit 2 }"
if errorlevel 1 goto :failed
del /Q "%TEMP_INFO_JSON%" >nul 2>&1

echo.
echo [2/4] 检查 conda 环境 "%ENV_NAME%"...
"%CONDA_EXE%" env list --json > "%TEMP_ENV_JSON%"
if errorlevel 1 (
    echo [错误] conda 环境查询失败；未尝试创建环境。
    goto :failed
)
powershell -NoProfile -Command "try { $v = Get-Content -LiteralPath $env:TEMP_ENV_JSON -Raw -Encoding UTF8 | ConvertFrom-Json; foreach ($p in $v.envs) { if ((Split-Path -Leaf $p) -eq $env:ENV_NAME) { exit 0 } }; exit 1 } catch { Write-Host ('[错误] 无法解析 conda env list JSON：' + $_.Exception.Message); exit 2 }"
if errorlevel 2 (
    echo [错误] 无法解析 conda 环境查询结果；未尝试创建环境。
    goto :failed
)
if errorlevel 1 goto :create_environment
echo [完成] 环境 "%ENV_NAME%" 已存在。
goto :validate_environment

:create_environment
echo [提示] 环境 "%ENV_NAME%" 不存在，正在从 "%YML_FILE%" 创建...
"%CONDA_EXE%" env create --name "%ENV_NAME%" --file "%YML_FILE%" -y
if errorlevel 1 (
    echo [错误] 创建 conda 环境 "%ENV_NAME%" 失败。
    goto :failed
)
echo [完成] 环境 "%ENV_NAME%" 创建完成。

:validate_environment
"%CONDA_EXE%" run --no-capture-output -n "%ENV_NAME%" python -c "import sys,sysconfig; print(sys.version.split()[0], sysconfig.get_platform()); raise SystemExit(0 if sys.version_info >= (3,10) and sysconfig.get_platform().lower() == 'win-amd64' else 1)"
if errorlevel 1 (
    echo [错误] 现有环境必须使用 Python 3.10+ 且平台为 win-amd64。
    echo        安装器不会自动升级或重建已有环境。
    goto :failed
)

echo.
echo [3/4] 安装并验证第三方依赖...
echo [提示] pip 会保留已满足的依赖，仅安装缺失或版本不匹配的依赖。
"%CONDA_EXE%" run --no-capture-output -n "%ENV_NAME%" python -m pip install --requirement "%REQUIREMENTS_FILE%"
if errorlevel 1 (
    echo [错误] 安装第三方依赖失败。
    goto :failed
)
"%CONDA_EXE%" run --no-capture-output -n "%ENV_NAME%" python -X utf8 -c "import pymupdf, pymupdf4llm"
if errorlevel 1 (
    echo [错误] 基础转换依赖导入验证失败。
    goto :failed
)
echo [完成] 基础 PDF 转换已就绪。

"%CONDA_EXE%" run -n "%ENV_NAME%" python -X utf8 -c "import runpy,sys; m=runpy.run_path(sys.argv[1]); m['check_ocr'](sys.argv[2])" "%EXTRACTOR_FILE%" "eng" >nul 2>&1
if errorlevel 1 (
    echo [提示] 英文 OCR 尚未就绪；基础转换不受影响。请参阅 references\ocr.md。
) else (
    echo [完成] 英文 OCR 已就绪。
)
"%CONDA_EXE%" run -n "%ENV_NAME%" python -X utf8 -c "import runpy,sys; m=runpy.run_path(sys.argv[1]); m['check_ocr'](sys.argv[2])" "%EXTRACTOR_FILE%" "chi_sim+eng" >nul 2>&1
if errorlevel 1 (
    echo [提示] 中英文 OCR 尚未就绪；需要 chi_sim 和 eng 语言数据。
) else (
    echo [完成] 中英文 OCR 已就绪。
)

echo.
echo [4/4] 安装 skill 到 AI agent...
echo.
echo   请选择要安装到哪款 AI agent：
echo     [1] Codex
echo     [2] Claude
choice /C 12 /N /M "  请输入 1 或 2："
if errorlevel 3 goto :choice_failed
if errorlevel 2 goto :select_claude
if errorlevel 1 goto :select_codex
goto :cancelled

:select_codex
set "AGENT_NAME=Codex"
set "AGENT_DIR=%USERPROFILE%\.codex"
goto :agent_selected

:select_claude
set "AGENT_NAME=Claude"
set "AGENT_DIR=%USERPROFILE%\.claude"

:agent_selected
if not exist "%AGENT_DIR%\" (
    echo [错误] 未找到 agent 配置目录："%AGENT_DIR%"
    goto :failed
)
set "SKILLS_DIR=%AGENT_DIR%\skills"
if not exist "%SKILLS_DIR%\" (
    echo [提示] 正在创建 skills 目录："%SKILLS_DIR%"
    mkdir "%SKILLS_DIR%"
    if errorlevel 1 goto :failed
)
set "SKILL_TARGET=%SKILLS_DIR%\%SKILL_NAME%"

echo.
if exist "%SKILL_TARGET%\" (
    echo [提示] %AGENT_NAME% 已安装 %SKILL_NAME%："%SKILL_TARGET%"
    choice /C YN /N /M "  是否覆盖？[Y/N] "
) else (
    echo   安装路径："%SKILL_TARGET%"
    choice /C YN /N /M "  确定要安装吗？[Y/N] "
)
if errorlevel 3 goto :choice_failed
if errorlevel 2 goto :cancelled
if errorlevel 1 goto :path_safety_check
goto :cancelled

:path_safety_check
powershell -NoProfile -Command "$s = [IO.Path]::GetFullPath($env:SCRIPT_DIR).TrimEnd('\'); $t = [IO.Path]::GetFullPath($env:SKILL_TARGET).TrimEnd('\'); if ($s -eq $t) { exit 10 }; if ($s.StartsWith($t + '\', [StringComparison]::OrdinalIgnoreCase) -or $t.StartsWith($s + '\', [StringComparison]::OrdinalIgnoreCase)) { exit 11 }; exit 0"
if errorlevel 11 (
    echo [错误] 安装源与目标目录互相包含，拒绝替换。
    goto :failed
)
if errorlevel 10 (
    echo [完成] 当前目录就是目标 skill；无需复制。
    goto :success
)

set "WORK_ROOT=%AGENT_DIR%\skill-install-work"
if not exist "%WORK_ROOT%\" mkdir "%WORK_ROOT%"
if errorlevel 1 (
    echo [错误] 无法创建安装工作目录："%WORK_ROOT%"
    goto :failed
)
set "STAGE_DIR=%WORK_ROOT%\%SKILL_NAME%.stage-%RANDOM%-%RANDOM%"
set "BACKUP_DIR=%WORK_ROOT%\%SKILL_NAME%.backup-%RANDOM%-%RANDOM%"
if exist "%STAGE_DIR%\" (
    echo [错误] 随机暂存目录已存在，请重新运行安装器："%STAGE_DIR%"
    goto :failed
)
if exist "%BACKUP_DIR%\" (
    echo [错误] 随机备份目录已存在，请重新运行安装器："%BACKUP_DIR%"
    goto :failed
)
mkdir "%STAGE_DIR%"
if errorlevel 1 goto :failed
mkdir "%STAGE_DIR%\scripts"
if errorlevel 1 goto :stage_failed
mkdir "%STAGE_DIR%\references"
if errorlevel 1 goto :stage_failed

copy /Y "%SCRIPT_DIR%pdf_read_env.yml" "%STAGE_DIR%\pdf_read_env.yml" >nul
if errorlevel 1 goto :stage_failed
copy /Y "%SCRIPT_DIR%pdf_read_env_requirements.txt" "%STAGE_DIR%\pdf_read_env_requirements.txt" >nul
if errorlevel 1 goto :stage_failed
copy /Y "%SCRIPT_DIR%SKILL.md" "%STAGE_DIR%\SKILL.md" >nul
if errorlevel 1 goto :stage_failed
copy /Y "%SCRIPT_DIR%README.md" "%STAGE_DIR%\README.md" >nul
if errorlevel 1 goto :stage_failed
copy /Y "%SCRIPT_DIR%pdf_2_md_main.py" "%STAGE_DIR%\pdf_2_md_main.py" >nul
if errorlevel 1 goto :stage_failed
copy /Y "%EXTRACTOR_FILE%" "%STAGE_DIR%\scripts\extract_pdf.py" >nul
if errorlevel 1 goto :stage_failed
copy /Y "%SCRIPT_DIR%references\ocr.md" "%STAGE_DIR%\references\ocr.md" >nul
if errorlevel 1 goto :stage_failed

fc /B "%YML_FILE%" "%STAGE_DIR%\pdf_read_env.yml" >nul
if errorlevel 1 goto :stage_failed
fc /B "%REQUIREMENTS_FILE%" "%STAGE_DIR%\pdf_read_env_requirements.txt" >nul
if errorlevel 1 goto :stage_failed
fc /B "%SCRIPT_DIR%SKILL.md" "%STAGE_DIR%\SKILL.md" >nul
if errorlevel 1 goto :stage_failed
fc /B "%SCRIPT_DIR%README.md" "%STAGE_DIR%\README.md" >nul
if errorlevel 1 goto :stage_failed
fc /B "%SCRIPT_DIR%pdf_2_md_main.py" "%STAGE_DIR%\pdf_2_md_main.py" >nul
if errorlevel 1 goto :stage_failed
fc /B "%EXTRACTOR_FILE%" "%STAGE_DIR%\scripts\extract_pdf.py" >nul
if errorlevel 1 goto :stage_failed
fc /B "%SCRIPT_DIR%references\ocr.md" "%STAGE_DIR%\references\ocr.md" >nul
if errorlevel 1 goto :stage_failed

if exist "%SKILL_TARGET%\" (
    move "%SKILL_TARGET%" "%BACKUP_DIR%" >nul
    if errorlevel 1 goto :stage_failed
)
move "%STAGE_DIR%" "%SKILL_TARGET%" >nul
if errorlevel 1 goto :activation_failed
set "STAGE_DIR="

fc /B "%YML_FILE%" "%SKILL_TARGET%\pdf_read_env.yml" >nul
if errorlevel 1 goto :verification_failed
fc /B "%REQUIREMENTS_FILE%" "%SKILL_TARGET%\pdf_read_env_requirements.txt" >nul
if errorlevel 1 goto :verification_failed
fc /B "%SCRIPT_DIR%SKILL.md" "%SKILL_TARGET%\SKILL.md" >nul
if errorlevel 1 goto :verification_failed
fc /B "%SCRIPT_DIR%README.md" "%SKILL_TARGET%\README.md" >nul
if errorlevel 1 goto :verification_failed
fc /B "%SCRIPT_DIR%pdf_2_md_main.py" "%SKILL_TARGET%\pdf_2_md_main.py" >nul
if errorlevel 1 goto :verification_failed
fc /B "%EXTRACTOR_FILE%" "%SKILL_TARGET%\scripts\extract_pdf.py" >nul
if errorlevel 1 goto :verification_failed
fc /B "%SCRIPT_DIR%references\ocr.md" "%SKILL_TARGET%\references\ocr.md" >nul
if errorlevel 1 goto :verification_failed

if defined BACKUP_DIR if exist "%BACKUP_DIR%\" rmdir /S /Q "%BACKUP_DIR%"
set "BACKUP_DIR="
if exist "%WORK_ROOT%\" rmdir "%WORK_ROOT%" >nul 2>&1

:success
echo.
echo ==========================================
echo   [完成] pdf_read 基础转换环境准备就绪
echo   [完成] %SKILL_NAME% skill 已安装到 %AGENT_NAME%
echo          路径："%SKILL_TARGET%"
echo ==========================================
goto :cleanup_success

:activation_failed
echo [错误] 无法激活暂存 skill，正在恢复旧版本...
if defined BACKUP_DIR if exist "%BACKUP_DIR%\" move "%BACKUP_DIR%" "%SKILL_TARGET%" >nul
if defined BACKUP_DIR if exist "%BACKUP_DIR%\" goto :rollback_failed
goto :stage_failed

:verification_failed
echo [错误] 新安装校验失败，正在恢复旧版本...
if exist "%SKILL_TARGET%\" rmdir /S /Q "%SKILL_TARGET%"
if defined BACKUP_DIR if exist "%BACKUP_DIR%\" move "%BACKUP_DIR%" "%SKILL_TARGET%" >nul
if defined BACKUP_DIR if exist "%BACKUP_DIR%\" goto :rollback_failed
goto :failed

:rollback_failed
echo [严重] 自动回滚失败。请保留并检查：
echo        暂存："%STAGE_DIR%"
echo        备份："%BACKUP_DIR%"
set "STAGE_DIR="
set "BACKUP_DIR="
goto :failed

:stage_failed
echo [错误] 暂存或复制 skill 文件失败；原安装未被删除。
if defined STAGE_DIR if exist "%STAGE_DIR%\" rmdir /S /Q "%STAGE_DIR%"
set "STAGE_DIR="
goto :failed

:choice_failed
echo [错误] 无法读取选择；未安装 skill。
goto :failed

:missing_yml
echo [错误] 未找到环境配置文件："%YML_FILE%"
goto :failed
:missing_requirements
echo [错误] 未找到依赖清单："%REQUIREMENTS_FILE%"
goto :failed
:missing_skill
echo [错误] 未找到 skill 说明："%SCRIPT_DIR%SKILL.md"
goto :failed
:missing_readme
echo [错误] 未找到 README："%SCRIPT_DIR%README.md"
goto :failed
:missing_wrapper
echo [错误] 未找到兼容入口："%SCRIPT_DIR%pdf_2_md_main.py"
goto :failed
:missing_extractor
echo [错误] 未找到提取脚本："%EXTRACTOR_FILE%"
goto :failed
:missing_ocr_guide
echo [错误] 未找到 OCR 指南："%SCRIPT_DIR%references\ocr.md"
goto :failed

:cancelled
echo [取消] 已取消安装。
goto :cleanup_success

:cleanup_success
if exist "%TEMP_ENV_JSON%" del /Q "%TEMP_ENV_JSON%" >nul 2>&1
if exist "%TEMP_INFO_JSON%" del /Q "%TEMP_INFO_JSON%" >nul 2>&1
exit /b 0

:failed
if exist "%TEMP_ENV_JSON%" del /Q "%TEMP_ENV_JSON%" >nul 2>&1
if exist "%TEMP_INFO_JSON%" del /Q "%TEMP_INFO_JSON%" >nul 2>&1
if defined STAGE_DIR if exist "%STAGE_DIR%\" rmdir /S /Q "%STAGE_DIR%"
echo.
echo 安装未完成。
exit /b 1
