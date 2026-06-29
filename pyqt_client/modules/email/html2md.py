"""HTML->Markdown 转换。与服务端 server/utils/html2md.py 完全一致，
保证客户端本地转出的 MD 和服务端自己转的结果相同（行为不变，只是把活前移到客户端）。"""
import re
import html2text

# NBSP / En space / Em space / Thin space / 窄不换行空格（用码点避免源码里出现不可见字符）
_SPECIAL_SPACES = [chr(c) for c in (0xA0, 0x2002, 0x2003, 0x2009, 0x202F)]


def html2md(html_content):
    if not html_content:
        return ''

    text_maker = html2text.HTML2Text()

    # --- 基础配置 ---
    text_maker.ignore_links = False
    text_maker.ignore_images = False
    text_maker.body_width = 0           # 禁用自动换行
    text_maker.ignore_emphasis = True   # 忽略加粗/斜体
    text_maker.single_line_break = True
    text_maker.wrap_links = False

    # --- 列表与缩进 ---
    text_maker.ul_item_mark = '-'
    text_maker.indent_list_items = True

    # --- 表格 ---
    text_maker.bypass_tables = False

    markdown_content = text_maker.handle(html_content)

    # 过滤无效图片占位符 ![]()
    markdown_content = re.sub(r'!\[\]\(\)', '', markdown_content)

    # 特殊空格归一
    for sp in _SPECIAL_SPACES:
        markdown_content = markdown_content.replace(sp, ' ')
    markdown_content = markdown_content.replace('&nbsp;', ' ')

    # 合并 3+ 换行 + 去首尾空白
    markdown_content = re.sub(r'\n{3,}', '\n\n', markdown_content)
    return markdown_content.strip()
