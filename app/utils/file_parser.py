import os
import pdfplumber
import docx


def extract_text_from_file(filepath):
    """
    根据文件后缀，提取 PDF 或 Word 中的文本
    """
    ext = os.path.splitext(filepath)[1].lower()
    text = ""

    try:
        if ext == '.pdf':
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"

        elif ext in ['.docx', '.doc']:
            doc = docx.Document(filepath)
            for para in doc.paragraphs:
                text += para.text + "\n"

        else:
            return ""  # 不支持的格式返回空

        return text.strip()

    except Exception as e:
        print(f"解析文件失败: {e}")
        return ""