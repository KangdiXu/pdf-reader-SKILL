### pdf-read skill 的README
pdf_read skill 是一个用于读取 PDF 文件内容的工具。它可以帮助用户提取 PDF 文件中的文本信息，方便后续的处理和分析。

#### 1、安装conda环境
创建名为pdf_read的conda环境
```bash
conda create -n pdf_read python=3.12 -y
conda activate pdf_read
```
当然，你也可以使用其他的环境管理工具，如uv来创建和管理你的 Python 环境，更为轻量化。下面主要介绍conda的使用
#### 2、安装依赖
在激活的pdf_read环境中，安装所需的依赖库：
```bash
pip install pymupdf4llm pathlib
```
其中 pymupdf4llm 是一个用于处理 PDF 文件的库，pathlib 是 Python 标准库中的一个模块，用于处理文件路径。

#### 3、激活conda环境并运行
激活conda环境并运行相应代码的指令如下（{CODE_BLOCK...}为具体代码，已经写在了SKILL.md中）
```bash
conda run pdf_read && python -c "
{CODE_BLOCK...}
"
```
需要调整的主要是`source /opt/anaconda3/bin/activate pdf_read && python -c`部分，根据你的系统环境和Python安装路径进行修改。在Windows系统中，激活环境的命令可能会有所不同，通常是：
```bash
conda activate pdf_read && python -c "
{CODE_BLOCK...}
"
```
请根据你的操作系统和环境管理工具的使用方式进行相应的调整。

#### 4、测试
已经将上述代码中的 `{INSERT_PDF_PATH_HERE}` 替换为当前目录测试的 PDF 文件的路径，然后运行代码。它将提取 PDF 文件中的文本并将其保存为 Markdown 格式，同时提取的图片将保存在一个文件夹中

##### 4.1 导入需要的python库
```python
import pymupdf4llm
import pathlib
import shutil
import subprocess,os,sys
```

- 下面是代码的主要部分。运行完成后，你可以查看生成的 Markdown 文件和图片文件夹，验证提取的内容是否正确。

-  注意：当你关闭这个测试环境时或经过120秒后，代码中的 `finally` 块会自动执行，清理生成的 Markdown 文件和图片文件夹，保持环境整洁。

##### 4.2 主体部分：解析PDF文件并提取文本和图片
```python
input_pdf_path='test_pdf_read_script.pdf' # 代替'{INSERT_PDF_PATH_HERE}'，直接使用当前目录下的PDF文件进行测试
pdf_path = pathlib.Path(input_pdf_path) 
cwd_path=pathlib.Path().absolute()
# 如果解析成功(是替身)，pdf_path将指向原始PDF文件；如果解析失败，pdf_path将指向输入路径（可能是别名文件）。后续代码将继续处理pdf_path，无论它是原始文件还是别名文件。
# 2. 设置图片保存的目录，例如：'你的PDF文件名-images'

# 防止文件名过长，截取前15个字符，并替换空格为下划线
temp_pdf_name = pdf_path.with_suffix('').name
if len(temp_pdf_name) > 15:
    temp_pdf_name = temp_pdf_name[0:15]
image_folder_str = temp_pdf_name.replace(' ', '_') + '_imgs' # 替换空格为下划线，避免文件夹名中有空格
# 将pdf临时复制
temp_pdf_path=(cwd_path/temp_pdf_name).with_suffix('.pdf')
shutil.copy2(str(pdf_path), str(temp_pdf_path))
image_folder_abs= cwd_path/image_folder_str
# 4. 调用提取函数
try:
    md_text = pymupdf4llm.to_markdown(
        temp_pdf_path,
        write_images=True,
        image_path=image_folder_str # 绝对不能有空格
    )
finally:    # 无论提取成功与否，都删除临时PDF文件
    if os.path.exists(str(temp_pdf_path)):
        os.remove(str(temp_pdf_path))

# 5. 检查图片文件夹是否为空，若为空则删除
if not any(image_folder_abs.iterdir()):
    shutil.rmtree(image_folder_abs)
    print('ℹ️ 该PDF中没有可提取的图片，未创建图片文件夹。')
else:
    print(f'🖼️ 图片已保存至: {image_folder_abs}')
    
# 将Markdown文本保存到文件
output_md = (cwd_path/pdf_path.name).with_suffix('.md') #pathlib.Path(pdf_path).with_suffix('.md')
output_md.write_text(md_text, encoding='utf-8')

print(f'✅ 文本已提取并保存至: {output_md}')

```