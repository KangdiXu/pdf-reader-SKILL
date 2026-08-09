import pymupdf4llm
import pathlib
import shutil
import os
import sys



def pdf_to_markdown(pdf_path: pathlib.Path, cwd_path=None):
    """将PDF转换为Markdown，提取图片，返回 (output_md, image_folder_abs)。"""
    if cwd_path is None:
        cwd_path = pdf_path.parent # 默认为PDF文件所在目录，图库文件夹也就放在这
    else:
        cwd_path = pathlib.Path(cwd_path)
    

    temp_pdf_name = pdf_path.with_suffix('').name
    if len(temp_pdf_name) > 15:
        temp_pdf_name = temp_pdf_name[:15]
    image_folder_str = temp_pdf_name.replace(' ', '_') + '_imgs'
    image_folder_abs = cwd_path / image_folder_str

    temp_pdf_path = (cwd_path / temp_pdf_name).with_suffix('.pdf')
    shutil.copy2(str(pdf_path), str(temp_pdf_path))

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

    if not any(image_folder_abs.iterdir()):
        shutil.rmtree(image_folder_abs)
        print('该PDF中没有可提取的图片，未创建图片文件夹。', flush=True)
        image_folder_abs = None
    else:
        print(f'图片已保存至: {image_folder_abs}', flush=True)
        # 打印所有图片的文件名
        print('提取的图片文件名列表:')
        for img_file in sorted(image_folder_abs.iterdir()):
            print(f'  {img_file.name}', flush=True)

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
    output_md, image_folder_abs=pdf_to_markdown(pdf_path)
    if pdf_path.name == test_demo_name: 
        input("按回车键继续清理生成的Markdown文件和图片文件夹...")       
        cleanup(output_md, image_folder_abs)


if __name__ == '__main__':
    main()
