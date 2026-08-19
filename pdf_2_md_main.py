import pymupdf4llm
import pathlib
import shutil
import os
import sys



def pdf_to_markdown(pdf_path: pathlib.Path, cwd_path=None):
    """将PDF转换为Markdown，提取图片，返回 (output_md, image_folder_abs)。"""
    if cwd_path is None:
        cwd_path = pathlib.Path.cwd() # 默认为当前工作目录，图库文件夹也就放在这
    else:
        cwd_path = pathlib.Path(cwd_path)

    if not pdf_path.exists():
        raise ValueError(f"输入文件{pdf_path}不存在")
    if not pdf_path.name.lower().endswith('.pdf'):
        raise ValueError(f"输入文件{pdf_path}必须是PDF格式")
    
    if not cwd_path.exists():
        raise ValueError(f"工作目录{cwd_path}不存在")
    if not cwd_path.is_dir():
        raise ValueError(f"工作目录{cwd_path}必须是一个文件夹")

    pdf_name_no_suffix = pdf_path.with_suffix('').name
    temp_pdf_name_len=15
    while temp_pdf_name_len<=len(pdf_name_no_suffix):
        # 创建临时PDF文件，避免原PDF文件被占用
        temp_pdf_name = pdf_name_no_suffix[:temp_pdf_name_len]
        temp_pdf_path = (cwd_path / temp_pdf_name).with_suffix('.pdf')
        if not temp_pdf_path.exists():
            shutil.copy2(str(pdf_path), str(temp_pdf_path))
            break
        temp_pdf_name_len += 1

    # 创建图片保存文件夹，文件夹名为临时PDF文件名加上'_imgs'后缀
    image_folder_str = temp_pdf_name.replace(' ', '_') + '_imgs'
    image_folder_abs = cwd_path / image_folder_str
    image_folder_str=str(image_folder_abs)
    
    print(f'正在解析PDF文件: {pdf_path}，图片保存目标路径: {image_folder_abs}，请稍候...', flush=True)
    try:
        md_text = pymupdf4llm.to_markdown(
            temp_pdf_path,
            write_images=True,
            image_path=image_folder_str,
        )
    finally:
        if os.path.exists(str(temp_pdf_path)):
            os.remove(str(temp_pdf_path))
    if image_folder_abs.exists():
        has_img_flag=any(image_folder_abs.iterdir())
    else:
        image_folder_abs.mkdir(parents=True, exist_ok=True)
        has_img_flag=False

    if has_img_flag:
        print(f'图片已保存至: {image_folder_abs}', flush=True)
        # 打印所有图片的文件名
        print('提取的图片文件名列表:')
        for img_file in sorted(image_folder_abs.iterdir()):
            print(f'  {img_file.name}', flush=True)
    else:
        shutil.rmtree(image_folder_abs)
        print('该PDF中没有可提取的图片，未创建图片文件夹。', flush=True)
        image_folder_abs = None
        

    output_md = (cwd_path / pdf_path.name).with_suffix('.md')
    output_md.write_text(md_text, encoding='utf-8')
    print(f'文本已提取并保存至: {output_md}', flush=True)
    return output_md, image_folder_abs



def cleanup(output_md, image_folder_abs):
    """清理生成的Markdown文件和图片文件夹。"""
    if output_md and os.path.exists(str(output_md)):
        os.remove(str(output_md))
    if image_folder_abs and os.path.exists(str(image_folder_abs)):
        shutil.rmtree(image_folder_abs)


def main():   
    test_demo_name='test_pdf_read_script.pdf'
    pdf_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent/test_demo_name 
    cwd_path = pathlib.Path(sys.argv[2]) if (len(sys.argv) >2 and sys.argv[2] != '') else None
    output_md, image_folder_abs=pdf_to_markdown(pdf_path, cwd_path)
    if pdf_path.name == test_demo_name: 
        input("按回车键继续清理生成的Markdown文件和图片文件夹...")       
        cleanup(output_md, image_folder_abs)


if __name__ == '__main__':
    main()
