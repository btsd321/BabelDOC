import os



# 遍历search_dir下所有pdf文件，将文件名绝对路径组合为字符串(空格分隔)并print
def collect_pdf_filenames():
    pdf_files = []
    for root, dirs, files in os.walk(search_dir):
        for file in files:
            if file.endswith('.pdf'):
                pdf_files.append(os.path.join(root, file))
    result_str = ' '.join(pdf_files)
    # 将"\"替换为"/" 
    result_str = result_str.replace('\\', '/')
    return result_str

if __name__ == '__main__':
    # 获取当前文件所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # 定义要搜索的目录
    search_dir = os.path.join(current_dir, 'input/file')
    print(collect_pdf_filenames())