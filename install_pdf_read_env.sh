#!/bin/bash
# ============================================================
# pdf-reader skill 环境安装脚本
# 1. 检查 conda 是否已安装
# 2. 检查 pdf_read 环境是否存在，不存在则创建
# 3. 对比 requirements.txt，安装缺失的第三方库
# 4. 选择目标 AI agent，安装 skill 到对应目录
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="pdf_read"
SKILL_NAME="pdf-reader"
REQUIREMENTS_FILE="$SCRIPT_DIR/pdf_read_env_requirements.txt"
YML_FILE="$SCRIPT_DIR/pdf_read_env.yml"

# ---- Agent 注册表（添加新 agent 只需在此处加一行） ----
# 格式: "显示名|配置目录|skills子目录"
AGENT_CODEX=("Codex" "$HOME/.codex" "skills")
AGENT_CLAUDE=("Claude" "$HOME/.claude" "skills")
# AGENT_FUTURE=("FutureAgent" "$HOME/.future_agent" "skills")  ← 示例

AGENT_LIST=(AGENT_CODEX AGENT_CLAUDE)
# ======================================================

# ---- 箭头选择菜单 ----
choose_agent() {
    local selected=0
    local count=$1
    shift
    local agents=("$@")

    # 隐藏光标
    tput civis 2>/dev/null
    trap 'tput cnorm 2>/dev/null' EXIT

    while true; do
        # 非首次渲染时，上移 count 行以便覆盖上一次的选项列表
        if [ -n "$rendered" ]; then
            printf '\033[%dA' "$count"
        fi
        rendered=1
        for i in "${!agents[@]}"; do
            if [ "$i" -eq "$selected" ]; then
                echo -e "\033[36m  ▸ ${agents[$i]}\033[0m\033[K"
            else
                echo -e "\033[2K    ${agents[$i]}"
            fi
        done

        # 读取按键
        read -rsn 1 key
        # 如果是 ESC 开头，补读剩余 2 字节（方向键的完整序列是 \033[A 或 \033[B）
        if [ "$key" = $'\033' ]; then
            read -rsn 2 key2
            key="$key$key2"
        fi
        case "$key" in
            $'\033[A'|$'k') ((selected--)); [ $selected -lt 0 ] && selected=$((count - 1)) ;;  # 上
            $'\033[B'|$'j') ((selected++)); [ $selected -ge $count ] && selected=0 ;;            # 下
            ''|$'\n'|$'\r') break ;;  # 回车确认
        esac
    done

    tput cnorm 2>/dev/null
    CHOOSE_AGENT_RESULT=$selected
}

echo "=========================================="
echo "  pdf-reader skill 环境安装"
echo "=========================================="

# ---- 1. 检查 conda ----
echo ""
echo "[1/4] 检查 conda..."

if ! command -v conda &> /dev/null; then
    echo "❌ 未检测到 conda。"
    echo "   请先安装 Miniconda 或 Anaconda："
    echo "   https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

CONDA_BASE=$(conda info --base 2>/dev/null)
echo "✅ conda 已安装 (base: $CONDA_BASE)"

# ---- 2. 检查/创建 pdf_read 环境 ----
echo ""
echo "[2/4] 检查 conda 环境 '$ENV_NAME'..."

if conda env list 2>/dev/null | grep -q "^${ENV_NAME} \|^${ENV_NAME}\*\| ${ENV_NAME} "; then
    echo "✅ 环境 '$ENV_NAME' 已存在，跳过创建。"
else
    echo "⚠️  环境 '$ENV_NAME' 不存在，正在从 pdf_read_env.yml 创建..."
    conda env create -f "$YML_FILE"
    echo "✅ 环境 '$ENV_NAME' 创建完成。"
fi

# ---- 3. 对比并安装缺失的第三方库 ----
echo ""
echo "[3/4] 对比第三方依赖..."

INSTALLED=$(conda run -n "$ENV_NAME" pip freeze 2>/dev/null | sed 's/[<>=!].*//' | tr '[:upper:]' '[:lower:]' | sort -u)

MISSING_PACKAGES=()
while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    pkg_name=$(echo "$line" | sed 's/[<>=!].*//' | tr '[:upper:]' '[:lower:]' | xargs)
    if ! echo "$INSTALLED" | grep -qx "$pkg_name"; then
        MISSING_PACKAGES+=("$line")
    fi
done < "$REQUIREMENTS_FILE"

if [ ${#MISSING_PACKAGES[@]} -eq 0 ]; then
    echo "✅ 所有依赖已安装，无需额外操作。"
else
    echo "⚠️  以下 ${#MISSING_PACKAGES[@]} 个包缺失，正在安装："
    for pkg in "${MISSING_PACKAGES[@]}"; do
        echo "   - $pkg"
    done
    conda run -n "$ENV_NAME" pip install "${MISSING_PACKAGES[@]}"
    echo "✅ 缺失依赖安装完成。"
fi

# ---- 4. 选择 agent 并安装 skill ----
echo ""
echo "[4/4] 安装 skill 到 AI agent..."
echo ""
echo "  请选择要安装到哪款 AI agent（↑↓ 键选择，回车确认）："
echo ""

# 构建 agent 显示名数组
AGENT_NAMES=()
for ref in "${AGENT_LIST[@]}"; do
    eval "info=(\"\${${ref}[@]}\")"
    AGENT_NAMES+=("${info[0]}")
done

choose_agent "${#AGENT_NAMES[@]}" "${AGENT_NAMES[@]}"
selected_idx=$CHOOSE_AGENT_RESULT

eval "agent_info=(\"\${${AGENT_LIST[$selected_idx]}[@]}\")"
AGENT_NAME="${agent_info[0]}"
AGENT_DIR="${agent_info[1]}"
AGENT_SKILLS_SUBDIR="${agent_info[2]}"

echo ""
echo "  已选择: $AGENT_NAME"
echo ""

# 检查 agent 配置目录
if [ ! -d "$AGENT_DIR" ]; then
    echo "❌ 未找到 $AGENT_DIR"
    echo "   可能没有安装 $AGENT_NAME 或未进行配置。"
    exit 1
fi

# 检查/创建 skills 目录
SKILLS_DIR="$AGENT_DIR/$AGENT_SKILLS_SUBDIR"
if [ ! -d "$SKILLS_DIR" ]; then
    echo "⚠️  未找到 $SKILLS_DIR，正在创建..."
    mkdir -p "$SKILLS_DIR"
    echo "✅ 已创建 $SKILLS_DIR"
fi

# 检查 skill 是否已存在
SKILL_TARGET="$SKILLS_DIR/$SKILL_NAME"
SKILL_SOURCE="$SCRIPT_DIR"

if [ -d "$SKILL_TARGET" ]; then
    echo ""
    echo "⚠️  $AGENT_NAME 已安装 $SKILL_NAME skill: $SKILL_TARGET"
    read -p "  是否覆盖？(y/N) " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "❌ 已取消安装。"
        exit 0
    fi
    rm -rf "$SKILL_TARGET"
else
    echo ""
    echo "  安装路径: $SKILL_TARGET"
    read -p "  确定要安装吗？(Y/n) " confirm
    if [ "$confirm" = "n" ] || [ "$confirm" = "N" ]; then
        echo "❌ 已取消安装。"
        exit 0
    fi
fi

# 复制 skill 文件（只复制必要的两个文件）
mkdir -p "$SKILL_TARGET"
cp "$SKILL_SOURCE/pdf_2_md_main.py" "$SKILL_TARGET/"
cp "$SKILL_SOURCE/SKILL.md" "$SKILL_TARGET/"

# 将 pdf_2_md_main.py 的实际路径写入 SKILL.md 中
# 在第一个 "### 0. 环境准备" 的下一行开始，依次写入标题和路径
PY_SCRIPT_PATH="$SKILL_TARGET/pdf_2_md_main.py"
awk -v py_path="$PY_SCRIPT_PATH" '
  /^### 0\. 环境准备/ && !done {
    print $0
    print ""
    print "**0a. skill 核心python脚本的路径**"
    print "AGENT_SKILL_py_PATH=" py_path
    done=1
    next
  }
  { print }
' "$SKILL_TARGET/SKILL.md" > "$SKILL_TARGET/SKILL.md.tmp" && mv "$SKILL_TARGET/SKILL.md.tmp" "$SKILL_TARGET/SKILL.md"
echo ""
echo "=========================================="
echo "  ✅ pdf_read 环境准备就绪！"
echo "  ✅ $SKILL_NAME skill 已安装到 $AGENT_NAME"
echo "     路径: $SKILL_TARGET"
echo "=========================================="
