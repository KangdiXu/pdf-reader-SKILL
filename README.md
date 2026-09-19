# pdf-reader 使用手册

`pdf-reader` 使用 PyMuPDF4LLM 转换或阅读本地 PDF。它优先读取文本，只有任务确实需要时才提取图片或运行 OCR。每次成功转换都会登记到一个 JSON 文件；只要 PDF 的 `source` 绝对路径已经有有效记录，默认就不再转换，不比较页数、图片、OCR、输出路径、文件修改时间或解析器版本。只有用户明确要求“忽略重复”“必须转换”等强制指令时才重新转换。

## 安装

macOS/Linux：

```bash
bash install_pdf_read_env.sh
```

Windows：

```bat
install_pdf_read_env.cmd
```

安装程序会创建或复用名为 `pdf_read` 的 Conda 环境，并把 `SKILL.md`、本手册、提取脚本和 OCR 指南安装到所选 AI agent。

本手册中的底层命令假设当前工作目录是 `pdf-reader`。如果从其他目录执行，请把 `scripts/extract_pdf.py` 和 `pdf_2_md_main.py` 替换为实际安装位置下的绝对路径。

## 如何向 Codex 使用这个 skill

通常不需要手动执行 Python。推荐把转换选项逐项写清楚：

```text
操作：<转换 / 阅读>
阅读对象：<PDF 文件绝对路径或目录绝对路径>
页数：<全文 / PDF 第 12-18 页 / 1-10,18,25-30>
图像：<不生成图片 / 生成选定页图片 / 生成所有处理页图片>
OCR：<自动 / 不使用 OCR / 强制 OCR>
OCR 语言：<无需 / eng / chi_sim+eng / 其他已安装语言>
任务：<可选，要总结、查找或核对什么>
输出目录：<可选，结果文件夹或批处理输出根目录>
重复处理：<默认 / 忽略重复，必须转换>（建议放在最后）
```

简短的单行写法也可以：

```text
转换这个文件夹所有 PDF 文件，全文，不生成图片，不使用 OCR。
```

格式化输入是推荐写法，不是强制语法；Codex 也会理解含义相同的自然语言。如果确实需要重新生成，把“忽略重复”或“必须转换”放在所有参数之后，例如：

```text
转换 report.pdf，全文，不生成图片，不使用 OCR，忽略重复，必须转换。
```

## “转换”和“阅读”的区别

- **转换（transfer）**：只把 PDF 转成 Markdown、逐页文件和按需图片，然后报告输出路径；不总结、不搜索、不解释输出内容。
- **阅读（read）**：先保证存在转换结果，再读取输出文件完成总结、搜索、问答、比较或事实提取。也就是说，阅读包含“必要时转换”这一步。

“转换这个 PDF”“导出为 Markdown”属于转换；“阅读并总结”“查找某个条款”“分析图表”属于阅读。底层 `pdf_2_md_main.py` 是 `extract_pdf.py` 的兼容入口，不是第二个转换步骤，同一次请求不要把两个入口各运行一遍。

建议提供以下信息：

1. 明确要求使用 `pdf-reader`。
2. 提供 PDF 文件或 PDF 所在目录的绝对路径。
3. 说明想解决的问题，而不仅是“读取 PDF”。
4. 说明处理全部文档、指定页码还是相关章节。
5. 说明是否需要分析图片、公式、图表或版式。
6. 提供用于保存提取结果的输出文件夹。

带分析目标的完整示例：

```text
请使用 pdf-reader。
操作：阅读
阅读对象：/Users/me/Documents/reports
页数：全文
图像：不生成图片
OCR：不使用 OCR
OCR 语言：无需
任务：逐份总结，并标注 PDF 页码
输出目录：/Users/me/Documents/reports-output
重复处理：默认
```

`--pages` 使用从 1 开始的 PDF 物理页码，不一定等于页面上印刷的书籍或期刊页码。

如果“阅读对象”是目录，默认只处理该目录第一层中的 `.pdf` 文件；只有用户明确要求时才递归处理子目录。每份 PDF 都会单独检查、单独转换，并写入独立的输出子目录，避免不同文件互相覆盖。`OCR 语言：无需` 表示不传 `--ocr-language`；脚本仍会在参数记录中保留默认值 `eng`，但在 `OCR：不使用 OCR` 时不会实际执行 OCR。

## 输出文件夹规则

`--output-dir` 表示强制转换或首次转换使用的最终结果文件夹。例如：

```bash
--output-dir "/Users/me/Documents/report-output"
```

结果会直接写入：

```text
/Users/me/Documents/report-output/
├── report.md
├── manifest.json
├── pages/
└── images/       # 仅按需存在
```

如果没有提供 `--output-dir`，默认在当前工作目录创建。短标识来自源 PDF 的绝对路径，用于避免不同目录下的同名 PDF 互相覆盖：

```text
<PDF文件名>-<source短标识>-pdf-reader-output/
```

默认在源 PDF 所在目录创建 `pdf-reader-conversions.json`，用于登记已经完成的转换。这样，即使后来请求另一个输出目录，也能根据同一个 `source` 找到原结果。源目录不可写时，可使用 `--registry-file` 指定一个可写的固定登记文件。

运行时先按下面唯一条件判断是否重复：

- 源 PDF 的绝对路径

登记中存在该 `source` 且结果仍然有效时，以下变化都**不会**自动重新转换：页数、图像模式、OCR 模式、OCR 语言、是否生成逐页文件、请求的输出目录、源文件大小或修改时间、PyMuPDF4LLM 版本。程序会返回登记中原有的结果位置，并同时返回已登记参数和本次请求参数，便于发现差异。

需要让新参数真正生效时，必须在指令末尾明确写“忽略重复”“必须转换”“强制转换”或“重新转换”。Skill 会把它映射成 `--reconvert`，也可以在命令行使用同义别名 `--force`。强制转换完成后，这个 `source` 的登记会更新为最新结果。

如果强制转换指定了新的输出目录，登记会改为指向新结果；旧输出目录不会自动删除，但不再是该 `source` 的当前登记结果。

只有登记项指向的输出文件夹、`manifest.json` 和生成文件结构都仍然有效时才会复用。否则会执行新转换。同一个输出文件夹需要重新生成时：

- 如果它为空，可以写入。
- 如果它是此前生成的完整 `pdf-reader` 输出，并且不包含额外文件，可以安全替换。
- 如果它包含其他文件或无法验证来源，程序拒绝覆盖，避免误删用户数据。

## 默认处理流程

```text
解析 source 绝对路径
  ↓
按 source 查询 pdf-reader-conversions.json
  ↓
该 source 已有有效结果？── 是 ──→ 不转换，报告登记中的结果文件夹
  │
  否
  ↓
检查 PDF，获得页数、目录、文本量、图片数和疑似扫描页
  ↓
选择页码、图片和 OCR 参数
  ↓
文本优先提取；只对疑似扫描页 OCR
  ↓
按需提取相关页面图片
  ↓
首次生成指定输出文件夹
  ↓
转换模式：报告文件路径并停止
阅读模式：读取相关页面并回答，同时标注 PDF 页码
```

## 场景一：只检查 PDF，不创建输出文件夹

适合先了解一本书、报告或未知 PDF 的基本结构。

向 Codex 提问：

```text
请使用 pdf-reader 检查 /Users/me/Documents/report.pdf。
告诉我页数、目录、文本量、图片数量以及是否包含疑似扫描页，不要提取全文。
```

Skill 处理方法：只运行快速检查，不执行布局分析、图片提取或 OCR。

底层命令：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  inspect "/Users/me/Documents/report.pdf"
```

输出结果：终端返回 JSON，包括 `page_count`、`text_chars`、`image_count`、`likely_scanned_pages`、文档元数据和目录；不会创建结果文件夹。

## 场景二：总结一份较短的普通 PDF

适合可正常复制文字的论文、报告或说明书。

向 Codex 提问：

```text
请使用 pdf-reader 阅读 /Users/me/Documents/paper.pdf。
总结研究问题、方法、主要结果、结论和研究局限，并为每部分标注 PDF 页码。
除非理解内容确有必要，否则不要提取图片。
把提取结果保存到 /Users/me/Documents/paper-output。
```

Skill 处理方法：先检查 PDF，然后提取全部页面文字；默认不提取图片，自动判断哪些页面需要 OCR。

底层命令：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  extract "/Users/me/Documents/paper.pdf" \
  --output-dir "/Users/me/Documents/paper-output"
```

输出结果：`paper-output/` 直接包含合并全文 `paper.md`、逐页文件 `pages/*.md` 和处理信息 `manifest.json`。Codex 根据这些文件生成带页码的总结。

## 场景三：在长文档中查找一个具体问题

适合几百页的手册、书籍、法规或技术规范。

向 Codex 提问：

```text
请使用 pdf-reader 在 /Users/me/Documents/device-manual.pdf 中查找
“冷却液压力不足”和错误代码 E104。
不要把整份文档加载进上下文；只读取搜索命中的页面及前后相关页面。
把提取结果保存到 /Users/me/Documents/manual-output。
```

Skill 处理方法：先检查目录；如果无法直接确定页码，则生成无图片的分页 Markdown，使用 `rg` 搜索关键词，只打开命中页和必要的相邻页。

底层命令：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  extract "/Users/me/Documents/device-manual.pdf" \
  --output-dir "/Users/me/Documents/manual-output" \
  --images none
```

然后搜索分页文件：

```bash
rg -n "冷却液压力不足|E104" "/Users/me/Documents/manual-output/pages"
```

输出结果：`manual-output/` 包含全文和逐页 Markdown，但 Codex 只读取命中的少量页面，不把整份手册放进上下文。

## 场景四：只阅读指定页码

适合已经知道目标章节或页码范围的情况。

向 Codex 提问：

```text
请使用 pdf-reader 阅读 /Users/me/Documents/book.pdf 的 PDF 第 35–52 页。
总结这一部分的核心观点，不处理其他页面，并标注页码。
把结果保存到 /Users/me/Documents/chapter-output。
```

Skill 处理方法：只解析第 35–52 页，避免处理文档其余部分。

底层命令：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  extract "/Users/me/Documents/book.pdf" \
  --output-dir "/Users/me/Documents/chapter-output" \
  --pages "35-52"
```

输出结果：`book.md` 和 `pages/` 只包含指定页面，`manifest.json` 记录处理参数和实际页数。

## 场景五：分析图表、公式或页面版式

适合论文插图、财务图表、流程图、复杂公式和依赖位置关系的页面。

向 Codex 提问：

```text
请使用 pdf-reader 阅读 /Users/me/Documents/experiment.pdf 的 PDF 第 12–15 页。
重点分析 Figure 3：解释每个子图、坐标轴、主要趋势，以及它是否支持正文结论。
提取这些页面中的图片，把结果保存到 /Users/me/Documents/figure-output。
```

Skill 处理方法：只处理指定页，同时提取这些页面中的图片。Codex结合 Markdown 和图片分析。

底层命令：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  extract "/Users/me/Documents/experiment.pdf" \
  --output-dir "/Users/me/Documents/figure-output" \
  --pages "12-15" \
  --images selected
```

输出结果：除 Markdown 和清单外，还生成 `images/`。Markdown 使用相对图片路径，因此整个输出文件夹可以移动。

## 场景六：数字生成型 PDF，只追求最快速度

适合确定具有正常文本层、无需 OCR 的 PDF。

向 Codex 提问：

```text
这个 PDF 有可复制文字。请使用 pdf-reader 阅读
/Users/me/Documents/specification.pdf 的第 20–40 页，关闭 OCR，
只总结技术实现部分，输出到 /Users/me/Documents/spec-output。
```

Skill 处理方法：关闭 OCR，只运行原生文本和布局提取。

底层命令：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  extract "/Users/me/Documents/specification.pdf" \
  --output-dir "/Users/me/Documents/spec-output" \
  --pages "20-40" \
  --ocr off
```

输出结果：生成指定页面的 Markdown，不进行昂贵的页面 OCR。这通常是最快的提取模式。

## 场景七：中文或中英文扫描件

适合没有文本层的扫描合同、档案、旧书或复印件。

向 Codex 提问：

```text
请使用 pdf-reader 处理 /Users/me/Documents/scanned-contract.pdf。
这是中文扫描件，只读取 PDF 第 1–8 页，强制 OCR，语言使用中文和英文。
提取合同双方、金额、日期和违约条款；姓名、金额和日期必须标注页码。
把结果保存到 /Users/me/Documents/contract-output。
```

Skill 处理方法：仅对指定页面强制 OCR，并使用请求的 OCR 语言。OCR 较慢，应尽量缩小页码范围。

底层命令：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  extract "/Users/me/Documents/scanned-contract.pdf" \
  --output-dir "/Users/me/Documents/contract-output" \
  --pages "1-8" \
  --ocr force \
  --ocr-language "chi_sim+eng"
```

输出结果：生成 OCR 后的 Markdown 和分页文件。OCR 语言是否可用取决于本机安装情况；关键姓名、数字和公式仍应与页面图像核对。

## 场景八：同时包含正常文字页和扫描页

适合部分页面为扫描附件的混合型 PDF。

向 Codex 提问：

```text
请使用 pdf-reader 阅读 /Users/me/Documents/mixed-report.pdf。
自动识别扫描页，只对确实需要的页面 OCR，然后给出完整摘要并标注页码。
把结果保存到 /Users/me/Documents/mixed-output。
```

Skill 处理方法：保留默认的 `--ocr auto`。脚本先检测每页的原生文本密度，只把疑似扫描页交给 OCR，正常文字页使用快速路径。

底层命令：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  extract "/Users/me/Documents/mixed-report.pdf" \
  --output-dir "/Users/me/Documents/mixed-output" \
  --ocr auto
```

输出结果：正常页面和 OCR 页面按照原页码重新合并；`manifest.json` 记录检测到的 `likely_scanned_pages`。

## 场景九：高精度核对表格、金额或统计数字

适合财报、实验数据表、合同金额等不能只相信文本提取的任务。

向 Codex 提问：

```text
请使用 pdf-reader 检查 /Users/me/Documents/financial-report.pdf 的 PDF 第 72–75 页。
提取收入、成本和同比变化，并结合页面图片复核每个数字。
把结果保存到 /Users/me/Documents/table-output。
```

Skill 处理方法：提取目标页面文本和图片，Codex交叉检查表格文字与视觉结果。

底层命令：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  extract "/Users/me/Documents/financial-report.pdf" \
  --output-dir "/Users/me/Documents/table-output" \
  --pages "72-75" \
  --images selected
```

输出结果：目标页 Markdown、逐页文件、表格或页面图片和处理清单。最终答案应逐项标注 PDF 页码，并说明无法可靠辨认的数据。

## 场景十：完整转换为 Markdown

适合需要保存、搜索、版本管理或供其他程序继续处理的文档。

向 Codex 提问：

```text
请使用 pdf-reader。
操作：转换
阅读对象：/Users/me/Documents/guide.pdf
页数：全文
图像：不生成图片
OCR：自动
OCR 语言：eng
输出目录：/Users/me/Documents/guide-output
重复处理：默认
```

Skill 处理方法：转换全部页面，保留合并文件和逐页文件，报告结果路径，但不读取或分析输出内容。

底层命令：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  transfer "/Users/me/Documents/guide.pdf" \
  --output-dir "/Users/me/Documents/guide-output" \
  --images none
```

如果只需要一个 Markdown 文件，可以增加：

```bash
--no-page-files
```

输出结果：默认生成 `guide.md`、`pages/` 和 `manifest.json`；使用 `--no-page-files` 时不生成 `pages/`。Codex 只报告这些路径和处理页数，不总结 PDF。

## 场景十一：source 已经转换过

只要登记中存在相同的源 PDF 绝对路径，就属于重复转换；参数和本次请求的输出位置不参与判断。

向 Codex 提问：

```text
请使用 pdf-reader 转换 /Users/me/Documents/report.pdf，
这次只要第 2 页、需要图片并强制中文 OCR，
输出写到 /Users/me/Documents/new-output。
如果 source 已经转换过，不要重新转换，告诉我原结果位置。
```

Skill 处理方法：仅按源文件绝对路径查询登记。即使这次参数和输出目录不同，也不执行转换，而是返回原登记的输出目录、原参数和本次请求参数。

底层命令：再次运行相同命令即可。

输出结果：不重新解析 PDF，返回 `status: already_converted`、原输出文件夹、`manifest.json`、`registered_parameters` 和 `requested_parameters`。`new-output` 不会被创建。

## 场景十二：目录中的所有 PDF

适合批量处理同一个目录下的论文、报告或账单。

向 Codex 提问：

```text
请使用 pdf-reader。
操作：转换
阅读对象：/Users/me/Documents/reports
页数：全文
图像：不生成图片
OCR：不使用 OCR
OCR 语言：无需
任务：逐份生成 Markdown，并给出每份文件的页数和结果路径
输出目录：/Users/me/Documents/reports-output
重复处理：默认
```

Skill 处理方法：默认枚举 `reports/` 第一层中的所有 PDF，不递归子目录；逐份运行 `transfer`。提取器先按 source 查重，只有没有有效登记或明确强制转换时才继续检查和转换 PDF。每份文件都有自己的结果文件夹和 `manifest.json`。如果要求“包括子文件夹”，才递归枚举并保留相对目录结构。

枚举第一层 PDF 的底层命令：

```bash
rg --files --max-depth 1 -g '*.pdf' -g '*.PDF' "/Users/me/Documents/reports"
```

如果用户明确要求递归处理，则去掉 `--max-depth 1`。

对其中 `annual-report.pdf` 执行的底层命令示例：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  extract "/Users/me/Documents/reports/annual-report.pdf" \
  --output-dir "/Users/me/Documents/reports-output/annual-report-pdf-reader-output" \
  --images none \
  --ocr off
```

其他 PDF 使用相同参数逐份执行。输出根目录中的每个 PDF 结果互相独立；默认登记文件位于源目录 `/Users/me/Documents/reports/pdf-reader-conversions.json`。

输出结果：Codex 汇总成功、已转换和失败的文件；不会因为一份 PDF 失败而把其他文件的结果混入同一文件夹。

## 场景十三：明确要求重新转换

如果要让新参数或新输出目录真正生效，或者已有结果需要重做，必须在自然语言指令最后明确写出强制要求：

```text
转换 /Users/me/Documents/report.pdf，PDF 第 2 页，生成选定页图片，
强制中文 OCR，输出到 /Users/me/Documents/report-output，忽略重复，必须转换。
```

对应底层命令使用 `--reconvert` 或同义别名 `--force`：

```bash
conda run --no-capture-output -n pdf_read python scripts/extract_pdf.py \
  transfer "/Users/me/Documents/report.pdf" \
  --output-dir "/Users/me/Documents/report-output" \
  --pages "2" \
  --images selected \
  --ocr force \
  --ocr-language "chi_sim" \
  --reconvert
```

这会跳过 source 重复记录，按照本次参数重新生成结果并更新该 source 的登记项。仅改变参数不会自动触发重新生成。

## 参数速查

| 参数 | 含义 | 适用场景 |
|---|---|---|
| `--output-dir "/path/result"` | 最终结果文件夹 | 指定输出位置 |
| `--registry-file "/path/pdf-reader-conversions.json"` | 指定转换登记 JSON | 源目录不可写或需要集中登记时 |
| `--reconvert` / `--force` | 忽略 source 重复记录并重新转换 | “忽略重复”“必须转换”等明确要求 |
| `--pages "1-10,18,25-30"` | 只处理指定的 1-based PDF 页码 | 已知章节或目标页 |
| `--images none` | 不提取图片，默认值 | 总结、搜索、普通文本分析 |
| `--images selected` | 提取明确指定页面的图片，必须配合 `--pages` | 图表、公式、表格、版式 |
| `--images all` | 提取所有已处理页面的图片 | 明确需要整份文档视觉内容时 |
| `--ocr auto` | 只对疑似扫描页 OCR，默认值 | 普通或混合型 PDF |
| `--ocr off` | 完全关闭 OCR | 确定具有正常文本层时 |
| `--ocr force` | 强制 OCR 所有选定页面 | 扫描件 |
| `--ocr-language chi_sim+eng` | 指定 OCR 语言 | 中英文扫描件 |
| `--no-page-files` | 不生成逐页 Markdown | 只需要一个合并文件时 |
| `--verbose` | 把解析器日志写入 stderr | 调试提取或 OCR 问题 |

## 输出结构

登记文件默认放在源 PDF 目录；结果文件夹可以位于其他位置：

```text
Documents/
├── report.pdf                   # source
├── pdf-reader-conversions.json  # 按 source 去重的登记表
└── report-a1b2c3d4-pdf-reader-output/
    ├── report.md                # 合并后的 Markdown，含 PDF 页码标记
    ├── manifest.json            # 当前输出文件夹的完整说明
    ├── pages/
    │   ├── 0001.md              # 单页 Markdown，便于搜索和选择性读取
    │   └── 0002.md
    └── images/                  # 仅在请求图片且实际提取到图片时存在
```

命令行返回的 JSON 示例：

```json
{
  "status": "ok",
  "already_converted": false,
  "output_dir": "/Users/me/Documents/report-output",
  "markdown": "/Users/me/Documents/report-output/report.md",
  "manifest": "/Users/me/Documents/report-output/manifest.json",
  "registry": "/Users/me/Documents/pdf-reader-conversions.json",
  "conversion_id": "...",
  "page_count": 12,
  "image_count": 0,
  "elapsed_seconds": 1.42
}
```

已经转换过时返回：

```json
{
  "status": "already_converted",
  "already_converted": true,
  "message": "该 source 已转换过；未重新转换。结果位于: /Users/me/Documents/report-output",
  "output_dir": "/Users/me/Documents/report-output",
  "requested_output_dir": "/Users/me/Documents/new-output",
  "markdown": "/Users/me/Documents/report-output/report.md",
  "manifest": "/Users/me/Documents/report-output/manifest.json",
  "registry": "/Users/me/Documents/pdf-reader-conversions.json",
  "conversion_id": "...",
  "parameters_ignored": true,
  "registered_parameters": {"pages": [1, 2, 3], "images": "none", "ocr": "off"},
  "requested_parameters": {"pages": "2", "images": "selected", "ocr": "force"}
}
```

## 转换登记 JSON 存储内容

`pdf-reader-conversions.json` 是多个转换结果的索引。每个登记项包含：

- `conversion_id`：只由源 PDF 绝对路径生成的稳定标识；参数和输出路径不参与计算
- `source`：源 PDF 绝对路径
- `source_size`、`source_mtime_ns`：生成时记录的信息，不参与重复判断
- `pymupdf4llm_version`：执行转换的解析器版本
- `parameters`：`pages`、`images`、`ocr`、`ocr_language`、`page_files`
- `output_dir`：转换结果文件夹绝对路径
- `output_folder`：转换结果文件夹名称
- `manifest`：该结果对应的 `manifest.json` 路径
- `generated_at`：生成时间

## manifest.json 存储内容

每个结果文件夹内的 `manifest.json` 只描述当前这一次转换，包含：

- `generator`、`schema_version`：生成器和清单格式版本
- `conversion_id`、`generated_at`：转换标识和生成时间
- `source`、`source_size`、`source_mtime_ns`：源文件身份与版本信息
- `output_dir`：本次转换绑定的输出文件夹绝对路径
- `pymupdf4llm_version`：解析器版本
- `parameters`：本次转换使用的全部参数
- `markdown_file`：按源文件名生成的合并 Markdown 文件名
- `pages_processed`：实际处理页数
- `likely_scanned_pages`：探测到的疑似扫描页
- `image_count`：输出图片数量
- `metadata`：PDF 自带的标题、作者、主题等元数据
- `toc`：PDF 目录
- `generated_files`、`generated_dirs`：由工具生成的文件和文件夹清单，用于验证结果是否完整，以及避免覆盖用户后来添加的文件

## 旧命令兼容

旧入口仍然有效：

```bash
conda run --no-capture-output -n pdf_read python pdf_2_md_main.py \
  "/Users/me/Documents/input.pdf" \
  "/Users/me/Documents/report-output" \
  --force
```

它会转发到新版 `extract` 命令，并保留输出目录后面的 `--pages`、`--images`、`--ocr`、`--reconvert` 或 `--force` 等选项。新代码和新文档应优先直接使用 `scripts/extract_pdf.py transfer`。不要对同一个请求同时运行两个入口。

## 测试

```bash
conda run --no-capture-output -n pdf_read python -m unittest discover -s tests -v
```
