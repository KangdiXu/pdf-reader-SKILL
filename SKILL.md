---
name: pdf-reader
description: "When user asks to read, extract text, or analyze a paper, an article, a guidebook, etc., generally belonging to a PDF file, this skill should be used. It activates a dedicated conda environment 'pdf_read' and uses PyMuPDF4LLM to process the file."
---

# PDF阅读专家

## 核心工作流
当被触发时，严格按以下步骤操作：

### 0. 环境准备



*上方空白插入python脚本路径*

`AGENT_SKILL_py_PATH` 是把**pdf转换为markdown的关键python脚本**的绝对路径，后面运行脚本时需要用到，非常重要。

在首次使用或遇到环境问题时，依次执行以下检查：

**0b. 检查 conda 环境是否存在**

```bash
conda env list | grep pdf_read 
```
如果存在问题，如conda指令无效、 `pdf_read` 环境不存在（`grep` 未匹配到），则停止处理对话内容，立刻向用户提示出现的问题，并告诉用户可行的解决方法。

### 1. 确认文件
获取用户提供的**PDF文件路径**或**macOS系统替身文件路径**。将 `INSERT_PDF_PATH_HERE` 直接替换为用户输入的要求阅读的PDF文件的**绝对路径**，运行python脚本。

### 2. 执行分析
使用以下命令在 `pdf_read` 环境中运行Python脚本，提取文字和图片。

### 3. 返回结果
将提取的Markdown文本和图片信息呈现给用户，并提示图片已保存的位置。

## 执行命令模板
下面是用于将**pdf转化为markdown的核心命令**。请**务必在当前对话的工作目录下**，创建一个子Shell命令完成环境激活和脚本执行。

```bash
AGENT_SKILL_py_PATH="/path/of/SKILL/py/script" # py脚本绝对路径在0.a部分已经给出
INSERT_PDF_PATH_HERE="/path/of/pdf/to/transfer" # 要转换的pdf的路径
OPTIONAL_RESULT_FOLDER="/path/of/results/output" # 转换得到的markdown和图片文件夹放置的文件夹路径，默认为当前工作目录
conda run --no-capture-output -n pdf_read python "$AGENT_SKILL_py_PATH" "$INSERT_PDF_PATH_HERE" "$OPTIONAL_RESULT_FOLDER"
```

**需要注意：**

- 把`AGENT_SKILL_py_PATH` 替换为当前AI-agent所用skill中的核心python脚本的绝对路径，`AGENT_SKILL_py_PATH` 使用的路径已经写在了本文档的 **0a. skill 核心python脚本的路径** 部分。

- 把 `INSERT_PDF_PATH_HERE` 替换为用户输入的要求阅读的PDF文件的**绝对路径**
- `OPTIONAL_RESULT_FOLDER` 是转换得到的markdown和图片文件夹放置的文件夹路径。**要关注用户命令中，关于转换后输出的文件放置路径的描述**。如果用户没有特殊要求就是**空字符**，python脚本会把转换结果放到**默认路径也就是当前工作目录**。
- 输入路径 `AGENT_SKILL_py_PATH`  、 `INSERT_PDF_PATH_HERE`  和`OPTIONAL_RESULT_FOLDER` 都是终端变量他们两边的英文双引号**必须**有，这样才能保证文件的路径即使有空格或者其他特殊的符号，也能正常运行python脚本，也是终端指令常用的格式，保证把**完整的、正确的字符串**传入到`pdf_2_md_main.py` 脚本

### 4. 其他注意事项

- skill运行过程中遇到python程序报错，立即结束当前将pdf转换为markdown的工作流，转向思考为什么会出错、SKILL 中的 `pdf_2_md_main.py ` 哪里有问题。

  
