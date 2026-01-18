import os


def print_tree_and_content(start_path="."):
    """
    遍历目录，打印文件树结构以及每个文件的内容。
    """

    # 配置：要忽略的文件夹
    IGNORE_DIRS = {
        '.git', '.idea', '.vscode', '__pycache__', 'venv', 'env',
        'node_modules', 'dist', 'build', '.DS_Store'
    }

    # 配置：要忽略的文件扩展名（二进制文件、图片等）
    IGNORE_EXTS = {
        # 音频 Audio
        '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma',
        # 视频 Video
        '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm',
        # 图片 Images
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.webp', '.tiff', '.psd',
        # 压缩包 Archives
        '.zip', '.tar', '.gz', '.rar', '.7z', '.bz2',
        # 文档 Documents (通常不包含可读代码)
        '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.csv',
        # 可执行/编译文件 Executables/Binaries
        '.exe', '.dll', '.so', '.dylib', '.bin', '.class', '.pyc', '.pyo', '.o', '.obj',
        # 其他数据库或设计文件
        '.db', '.sqlite', '.sqlite3', '.sketch', '.fig', '.DS_Store'
    }

    print(f"Project Root: {os.path.abspath(start_path)}\n")

    for root, dirs, files in os.walk(start_path):
        # 修改 dirs 列表，移除需要忽略的文件夹，这样 os.walk 就不会进入这些目录
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        # 计算当前层级，用于缩进
        level = root.replace(start_path, '').count(os.sep)
        indent = '    ' * level

        # 打印当前文件夹名称
        folder_name = os.path.basename(root)
        if folder_name == '': folder_name = '.'
        print(f"{indent}📁 {folder_name}/")

        sub_indent = '    ' * (level + 1)

        for file in files:
            # 检查扩展名是否应该忽略
            ext = os.path.splitext(file)[1].lower()
            if ext in IGNORE_EXTS:
                print(f"{sub_indent}📄 {file} [Skipped Binary/Ignored]")
                continue

            file_path = os.path.join(root, file)
            print(f"{sub_indent}📄 {file}")

            # 尝试读取并打印文件内容
            try:
                # 优先尝试 UTF-8
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    print_file_content(sub_indent, file, content)
            except UnicodeDecodeError:
                # 如果 UTF-8 失败，尝试 Latin-1 (通常能读取部分非标准编码)
                try:
                    with open(file_path, 'r', encoding='latin-1') as f:
                        content = f.read()
                        print_file_content(sub_indent, file, content)
                except Exception:
                    print(f"{sub_indent}    [Error: Cannot decode file content]")
            except Exception as e:
                print(f"{sub_indent}    [Error reading file: {e}]")


def print_file_content(indent, filename, content):
    """辅助函数：格式化打印文件内容"""
    print(f"{indent}    {'=' * 20} START OF {filename} {'=' * 20}")
    # 打印内容，每行前面加一点缩进以便区分
    # 如果不想内容被缩进，可以将 replace 去掉
    print(content)
    print(f"{indent}    {'=' * 20} END OF {filename} {'=' * 20}")
    print("")  # 空一行


if __name__ == "__main__":
    # 默认从当前脚本所在目录开始
    print_tree_and_content(".")