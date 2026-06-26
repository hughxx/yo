"""html2md —— HTML → Markdown 命令行工具（复用 server/utils/html2md.py 的 html2text 逻辑）。

约定：
- 从 stdin 读取 HTML（UTF-8），向 stdout 写出 Markdown（UTF-8）。
- 纯文本转换，不依赖 Outlook / win32com，体积小。
"""
import re
import sys

import html2text


def html2md(html_content: str) -> str:
    if not html_content:
        return ''

    text_maker = html2text.HTML2Text()
    # 基础配置
    text_maker.ignore_links = False
    text_maker.ignore_images = False
    text_maker.body_width = 0          # 禁用自动换行
    text_maker.ignore_emphasis = True  # 忽略加粗/斜体
    text_maker.single_line_break = True
    text_maker.wrap_links = False
    # 列表与缩进
    text_maker.ul_item_mark = '-'
    text_maker.indent_list_items = True
    # 表格
    text_maker.bypass_tables = False

    markdown_content = text_maker.handle(html_content)

    # 后处理
    markdown_content = re.sub(r'!\[\]\(\)', '', markdown_content)
    # 各种特殊空格归一化：NBSP / En / Em / Thin / Narrow NBSP
    for cp in (0xA0, 0x2002, 0x2003, 0x2009, 0x202F):
        markdown_content = markdown_content.replace(chr(cp), ' ')
    markdown_content = markdown_content.replace('&nbsp;', ' ')
    markdown_content = re.sub(r'\n{3,}', '\n\n', markdown_content)
    return markdown_content.strip()


def main() -> int:
    raw = sys.stdin.buffer.read().decode('utf-8', 'replace')
    md = html2md(raw)
    sys.stdout.buffer.write(md.encode('utf-8'))
    sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    # 用 Exception 而非 BaseException：否则正常结束的 SystemExit(0) 会被这里捕获，
    # 把退出码 "0" 写进 stderr 再以 1 退出，吞掉转换结果。
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        sys.stderr.buffer.write(str(e).encode('utf-8', 'replace'))
        sys.exit(1)
