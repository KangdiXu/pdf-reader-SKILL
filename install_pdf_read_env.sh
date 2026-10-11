#!/bin/bash
# pdf-reader skill installer for macOS/Linux.
# Skill replacement is staged and rolled back if activation or validation fails.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_NAME="pdf_read"
SKILL_NAME="pdf-reader"
REQUIREMENTS_FILE="$SCRIPT_DIR/pdf_read_env_requirements.txt"
YML_FILE="$SCRIPT_DIR/pdf_read_env.yml"
EXTRACTOR_FILE="$SCRIPT_DIR/scripts/extract_pdf.py"
ENV_JSON=""
STAGE_DIR=""
BACKUP_DIR=""
CURSOR_HIDDEN=0

cleanup() {
    if [ "$CURSOR_HIDDEN" -eq 1 ]; then
        tput cnorm >/dev/null 2>&1 || true
    fi
    if [ -n "$ENV_JSON" ] && [ -f "$ENV_JSON" ]; then
        rm -f "$ENV_JSON"
    fi
    if [ -n "$STAGE_DIR" ] && [ -d "$STAGE_DIR" ]; then
        rm -rf "$STAGE_DIR"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

required_files=(
    "pdf_read_env.yml"
    "pdf_read_env_requirements.txt"
    "SKILL.md"
    "README.md"
    "pdf_2_md_main.py"
    "scripts/extract_pdf.py"
    "references/ocr.md"
)
for relative in "${required_files[@]}"; do
    if [ ! -f "$SCRIPT_DIR/$relative" ]; then
        echo "[错误] 缺少安装文件：$SCRIPT_DIR/$relative" >&2
        exit 1
    fi
done

AGENT_CODEX=("Codex" "$HOME/.codex" "skills")
AGENT_CLAUDE=("Claude" "$HOME/.claude" "skills")
AGENT_LIST=(AGENT_CODEX AGENT_CLAUDE)

choose_agent_numeric() {
    local answer
    echo "  [1] Codex"
    echo "  [2] Claude"
    while true; do
        if ! IFS= read -r -p "  请输入 1 或 2（EOF 取消）：" answer; then
            return 1
        fi
        case "$answer" in
            1) CHOOSE_AGENT_RESULT=0; return 0 ;;
            2) CHOOSE_AGENT_RESULT=1; return 0 ;;
            *) echo "  请输入 1 或 2。" ;;
        esac
    done
}

choose_agent() {
    local selected=0
    local count=$1
    local rendered=0
    local key=""
    local key2=""
    local i
    shift
    local agents=("$@")

    if [ ! -t 0 ] || [ ! -t 1 ] || ! command -v tput >/dev/null 2>&1 ||
       ! tput cols >/dev/null 2>&1; then
        choose_agent_numeric
        return
    fi

    tput civis >/dev/null 2>&1 || true
    CURSOR_HIDDEN=1
    while true; do
        if [ "$rendered" -eq 1 ]; then
            printf '\033[%dA' "$count"
        fi
        rendered=1
        for ((i = 0; i < count; i++)); do
            if [ "$i" -eq "$selected" ]; then
                printf '\033[36m  ▸ %s\033[0m\033[K\n' "${agents[$i]}"
            else
                printf '\033[2K    %s\n' "${agents[$i]}"
            fi
        done

        if ! IFS= read -rsn 1 key; then
            tput cnorm >/dev/null 2>&1 || true
            CURSOR_HIDDEN=0
            return 1
        fi
        if [ "$key" = $'\033' ]; then
            if ! IFS= read -rsn 2 key2; then
                tput cnorm >/dev/null 2>&1 || true
                CURSOR_HIDDEN=0
                return 1
            fi
            key="$key$key2"
        fi
        case "$key" in
            $'\033[A'|k)
                selected=$((selected - 1))
                [ "$selected" -lt 0 ] && selected=$((count - 1))
                ;;
            $'\033[B'|j)
                selected=$((selected + 1))
                [ "$selected" -ge "$count" ] && selected=0
                ;;
            ''|$'\n'|$'\r') break ;;
        esac
    done
    tput cnorm >/dev/null 2>&1 || true
    CURSOR_HIDDEN=0
    CHOOSE_AGENT_RESULT=$selected
}

echo "=========================================="
echo "  pdf-reader skill 环境安装"
echo "=========================================="
echo
echo "[1/4] 检查 conda..."
if ! command -v conda >/dev/null 2>&1; then
    echo "[错误] 未检测到 conda。请先安装 Miniconda 或 Anaconda。" >&2
    exit 1
fi
if ! CONDA_BASE="$(conda info --base 2>/dev/null)" || [ -z "$CONDA_BASE" ]; then
    echo "[错误] conda 可执行，但无法读取 base 环境路径。" >&2
    exit 1
fi
echo "[完成] conda 已安装 (base: \"$CONDA_BASE\")"

echo
echo "[2/4] 检查 conda 环境 \"$ENV_NAME\"..."
ENV_JSON="$(mktemp "${TMPDIR:-/tmp}/pdf-reader-envs.XXXXXX")"
if ! conda env list --json > "$ENV_JSON"; then
    echo "[错误] conda 环境查询失败；未尝试创建环境。" >&2
    exit 1
fi
if conda run -p "$CONDA_BASE" python -c 'import json,os,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if isinstance(data, dict) and any(os.path.basename(os.path.normpath(p)) == sys.argv[2] for p in data.get("envs", [])) else 3)' "$ENV_JSON" "$ENV_NAME"; then
    echo "[完成] 环境 \"$ENV_NAME\" 已存在。"
else
    status=$?
    if [ "$status" -ne 3 ]; then
        echo "[错误] 无法解析 conda 环境查询结果；未尝试创建环境。" >&2
        exit 1
    fi
    echo "[提示] 环境 \"$ENV_NAME\" 不存在，正在从 \"$YML_FILE\" 创建..."
    conda env create --name "$ENV_NAME" --file "$YML_FILE"
    echo "[完成] 环境 \"$ENV_NAME\" 创建完成。"
fi

if ! conda run --no-capture-output -n "$ENV_NAME" python -c 'import sys; print(sys.version.split()[0]); raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
    echo "[错误] 现有环境必须使用 Python 3.10+；安装器不会自动升级或重建它。" >&2
    exit 1
fi

echo
echo "[3/4] 安装并验证第三方依赖..."
conda run --no-capture-output -n "$ENV_NAME" python -m pip install --requirement "$REQUIREMENTS_FILE"
conda run --no-capture-output -n "$ENV_NAME" python -X utf8 -c "import pymupdf, pymupdf4llm"
echo "[完成] 基础 PDF 转换已就绪。"

if conda run -n "$ENV_NAME" python -X utf8 -c "import runpy,sys; m=runpy.run_path(sys.argv[1]); m['check_ocr'](sys.argv[2])" "$EXTRACTOR_FILE" "eng" >/dev/null 2>&1; then
    echo "[完成] 英文 OCR 已就绪。"
else
    echo "[提示] 英文 OCR 尚未就绪；基础转换不受影响。请参阅 references/ocr.md。"
fi
if conda run -n "$ENV_NAME" python -X utf8 -c "import runpy,sys; m=runpy.run_path(sys.argv[1]); m['check_ocr'](sys.argv[2])" "$EXTRACTOR_FILE" "chi_sim+eng" >/dev/null 2>&1; then
    echo "[完成] 中英文 OCR 已就绪。"
else
    echo "[提示] 中英文 OCR 尚未就绪；需要 chi_sim 和 eng 语言数据。"
fi

echo
echo "[4/4] 安装 skill 到 AI agent..."
echo "  请选择要安装到哪款 AI agent（方向键或数字菜单）："
echo
AGENT_NAMES=()
for ref in "${AGENT_LIST[@]}"; do
    eval "info=(\"\${${ref}[@]}\")"
    AGENT_NAMES+=("${info[0]}")
done
if ! choose_agent "${#AGENT_NAMES[@]}" "${AGENT_NAMES[@]}"; then
    echo "[取消] 输入已结束，未安装 skill。"
    exit 0
fi
selected_idx=$CHOOSE_AGENT_RESULT
eval "agent_info=(\"\${${AGENT_LIST[$selected_idx]}[@]}\")"
AGENT_NAME="${agent_info[0]}"
AGENT_DIR="${agent_info[1]}"
AGENT_SKILLS_SUBDIR="${agent_info[2]}"

if [ ! -d "$AGENT_DIR" ]; then
    echo "[错误] 未找到 agent 配置目录：\"$AGENT_DIR\"" >&2
    exit 1
fi
SKILLS_DIR="$AGENT_DIR/$AGENT_SKILLS_SUBDIR"
mkdir -p "$SKILLS_DIR"
SKILL_TARGET="$SKILLS_DIR/$SKILL_NAME"

echo
if [ -d "$SKILL_TARGET" ]; then
    echo "[提示] $AGENT_NAME 已安装 $SKILL_NAME：\"$SKILL_TARGET\""
    if ! IFS= read -r -p "  是否覆盖？[y/N] " confirm; then
        echo "[取消] 输入已结束，未安装 skill。"
        exit 0
    fi
    case "$confirm" in y|Y) ;; *) echo "[取消] 已取消安装。"; exit 0 ;; esac
else
    echo "  安装路径：\"$SKILL_TARGET\""
    if ! IFS= read -r -p "  确定要安装吗？[Y/n] " confirm; then
        echo "[取消] 输入已结束，未安装 skill。"
        exit 0
    fi
    case "$confirm" in n|N) echo "[取消] 已取消安装。"; exit 0 ;; esac
fi

SOURCE_REAL="$SCRIPT_DIR"
TARGET_REAL="$(cd "$(dirname "$SKILL_TARGET")" && pwd -P)/$(basename "$SKILL_TARGET")"
if [ "$SOURCE_REAL" = "$TARGET_REAL" ]; then
    echo "[完成] 当前目录就是目标 skill；无需复制。"
    exit 0
fi
case "$SOURCE_REAL/" in "$TARGET_REAL/"*) echo "[错误] 安装源位于目标目录内，拒绝替换。" >&2; exit 1 ;; esac
case "$TARGET_REAL/" in "$SOURCE_REAL/"*) echo "[错误] 目标目录位于安装源内，拒绝替换。" >&2; exit 1 ;; esac

WORK_ROOT="$AGENT_DIR/skill-install-work"
mkdir -p "$WORK_ROOT"
STAGE_DIR="$(mktemp -d "$WORK_ROOT/$SKILL_NAME.stage.XXXXXX")"
BACKUP_DIR="$WORK_ROOT/$SKILL_NAME.backup.$$"
while [ -e "$BACKUP_DIR" ]; do
    BACKUP_DIR="$WORK_ROOT/$SKILL_NAME.backup.$$.$RANDOM"
done

mkdir -p "$STAGE_DIR/scripts" "$STAGE_DIR/references"
cp "$YML_FILE" "$STAGE_DIR/pdf_read_env.yml"
cp "$REQUIREMENTS_FILE" "$STAGE_DIR/pdf_read_env_requirements.txt"
cp "$SCRIPT_DIR/SKILL.md" "$STAGE_DIR/SKILL.md"
cp "$SCRIPT_DIR/README.md" "$STAGE_DIR/README.md"
cp "$SCRIPT_DIR/pdf_2_md_main.py" "$STAGE_DIR/pdf_2_md_main.py"
cp "$EXTRACTOR_FILE" "$STAGE_DIR/scripts/extract_pdf.py"
cp "$SCRIPT_DIR/references/ocr.md" "$STAGE_DIR/references/ocr.md"
cmp "$YML_FILE" "$STAGE_DIR/pdf_read_env.yml"
cmp "$REQUIREMENTS_FILE" "$STAGE_DIR/pdf_read_env_requirements.txt"
cmp "$SCRIPT_DIR/SKILL.md" "$STAGE_DIR/SKILL.md"
cmp "$SCRIPT_DIR/README.md" "$STAGE_DIR/README.md"
cmp "$SCRIPT_DIR/pdf_2_md_main.py" "$STAGE_DIR/pdf_2_md_main.py"
cmp "$EXTRACTOR_FILE" "$STAGE_DIR/scripts/extract_pdf.py"
cmp "$SCRIPT_DIR/references/ocr.md" "$STAGE_DIR/references/ocr.md"

had_backup=0
if [ -d "$SKILL_TARGET" ]; then
    mv "$SKILL_TARGET" "$BACKUP_DIR"
    had_backup=1
fi
if ! mv "$STAGE_DIR" "$SKILL_TARGET"; then
    if [ "$had_backup" -eq 1 ] && ! mv "$BACKUP_DIR" "$SKILL_TARGET"; then
        echo "[严重] 激活失败且自动回滚失败；备份保留在：$BACKUP_DIR" >&2
        STAGE_DIR=""
        BACKUP_DIR=""
        exit 1
    fi
    if [ "$had_backup" -eq 1 ]; then
        echo "[错误] 无法激活暂存 skill；旧版本已恢复。" >&2
    else
        echo "[错误] 无法激活暂存 skill；未留下不完整安装。" >&2
    fi
    exit 1
fi
STAGE_DIR=""

if ! cmp "$YML_FILE" "$SKILL_TARGET/pdf_read_env.yml" ||
   ! cmp "$REQUIREMENTS_FILE" "$SKILL_TARGET/pdf_read_env_requirements.txt" ||
   ! cmp "$SCRIPT_DIR/SKILL.md" "$SKILL_TARGET/SKILL.md" ||
   ! cmp "$SCRIPT_DIR/README.md" "$SKILL_TARGET/README.md" ||
   ! cmp "$SCRIPT_DIR/pdf_2_md_main.py" "$SKILL_TARGET/pdf_2_md_main.py" ||
   ! cmp "$EXTRACTOR_FILE" "$SKILL_TARGET/scripts/extract_pdf.py" ||
   ! cmp "$SCRIPT_DIR/references/ocr.md" "$SKILL_TARGET/references/ocr.md"; then
    if ! rm -rf "$SKILL_TARGET"; then
        if [ "$had_backup" -eq 1 ]; then
            echo "[严重] 无法移除校验失败的新安装；旧版本备份保留在：$BACKUP_DIR" >&2
        else
            echo "[严重] 无法移除校验失败的新安装：$SKILL_TARGET" >&2
        fi
        BACKUP_DIR=""
        exit 1
    fi
    if [ "$had_backup" -eq 1 ] && ! mv "$BACKUP_DIR" "$SKILL_TARGET"; then
        echo "[严重] 安装校验失败且自动回滚失败；备份保留在：$BACKUP_DIR" >&2
        BACKUP_DIR=""
        exit 1
    fi
    if [ "$had_backup" -eq 1 ]; then
        echo "[错误] 新安装校验失败；旧版本已恢复。" >&2
    else
        echo "[错误] 新安装校验失败；未留下不完整安装。" >&2
    fi
    exit 1
fi

if [ "$had_backup" -eq 1 ]; then
    rm -rf "$BACKUP_DIR"
fi
BACKUP_DIR=""
rmdir "$WORK_ROOT" >/dev/null 2>&1 || true

echo
echo "=========================================="
echo "  [完成] pdf_read 基础转换环境准备就绪"
echo "  [完成] $SKILL_NAME skill 已安装到 $AGENT_NAME"
echo "         路径：\"$SKILL_TARGET\""
echo "=========================================="
