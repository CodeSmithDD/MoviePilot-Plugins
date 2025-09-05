import re

def _clean_filename(filename: str):
    # 定义常见全角符号到半角符号的映射，或直接移除
    cleaned_filename = filename
    fullwidth_to_halfwidth = {
        '\uFF0D': '-',  # 全角破折号（－）替换为半角连字符（-）
        '\uFF1A': ':',  # 全角冒号（：）替换为半角冒号（:）
        '\uFF0C': ',',  # 全角逗号（，）替换为半角逗号（,）
        '\uFF0E': '.',  # 全角句号（。）替换为半角句号（.）
        '\uFF01': '!',  # 全角感叹号（！）替换为半角感叹号（!）
        '\uFF1F': '?',  # 全角问号（？）替换为半角问号（?）
        '\uFF08': '(',  # 全角左括号（（）替换为半角左括号（(）
        '\uFF09': ')',  # 全角右括号（））替换为半角右括号（)）
        '\uFF3B': '[',  # 全角左方括号（［）替换为半角左方括号（[）
        '\uFF3D': ']',  # 全角右方括号（］）替换为半角右方括号（]）
        '\u3000': ' ',  # 全角空格替换为半角空格
        # 其他全角符号可以直接移除（例如全角顿号、引号等）
        '\u3001': '',  # 全角顿号（、）
        '\u3002': '.',  # 全角句号（。）
        '\u201C': '"',  # 全角左双引号
        '\u201D': '"',  # 全角右双引号
        '\u2018': '\'',  # 全角左单引号
        '\u2019': '\'',  # 全角右单引号
    }

    # 替换全角符号
    for fullwidth, halfwidth in fullwidth_to_halfwidth.items():
        cleaned_filename = cleaned_filename.replace(fullwidth, halfwidth)

    # 去掉中文和中文之间的空格
    cleaned_filename = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', cleaned_filename)

    # 去掉中文和英文之间的空格
    cleaned_filename = re.sub(r'([\u4e00-\u9fff]+)\s+([a-zA-Z0-9]+)\s*([\u4e00-\u9fff]+)', r'\1\2\3',
                              cleaned_filename)
    cleaned_filename = re.sub(r'([\u4e00-\u9fff]+)\s+([a-zA-Z0-9]+)', r'\1\2',
                              cleaned_filename)
    cleaned_filename = re.sub(r'([a-zA-Z0-9]+)\s+([\u4e00-\u9fff]+)', r'\1\2',
                              cleaned_filename)

    # 将中文和中文之间的“-”替换为空格
    cleaned_filename = re.sub(r'([\u4e00-\u9fff])\s*-([\u4e00-\u9fff])', r'\1 \2', cleaned_filename)
    # 将中文和“-”替换为中文
    cleaned_filename = re.sub(r'([\u4e00-\u9fff])(-)', r'\1', cleaned_filename)

    return cleaned_filename

