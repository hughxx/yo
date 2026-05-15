import re
import html2text


def html2md(html_content):
    if not html_content:
        return ''

    # 创建 html2text 对象
    text_maker = html2text.HTML2Text()

    # --- 基础配置 ---
    text_maker.ignore_links = False
    text_maker.ignore_images = False
    text_maker.body_width = 0  # 禁用自动换行
    text_maker.ignore_emphasis = True  # 忽略加粗/斜体
    text_maker.single_line_break = True  # 尽量减少不必要的空行
    text_maker.wrap_links = False  # 链接不换行

    # --- B. 列表与缩进配置 ---
    text_maker.ul_item_mark = '-'  # 统一使用 '-' 作为无序列表符号
    text_maker.indent_list_items = True  # 启用列表缩进，确保嵌套层级清晰

    # --- C. 表格支持 ---
    text_maker.bypass_tables = False  # 尝试将 HTML 表格转换为 Markdown 表格

    # 执行转换
    markdown_content = text_maker.handle(html_content)

    # --- D. 图片处理与后处理优化 ---

    # 1. 过滤掉没有 Alt 文本且没有 URL 的无效图片占位符 ![]()
    # 或者过滤掉只有图片标记但实际无法显示的空链接
    markdown_content = re.sub(r'!\[\]\(\)', '', markdown_content)

    # 2. 处理特殊空格（\xa0 是不换行空格，\u2003 是全角空格）
    # A. 替换各种形式的 NBSP 和特殊空格
    # \xa0: 标准 NBSP
    # \u2002, \u2003, \u2009: 各种宽度的特殊空格 (En space, Em space, Thin space)
    # \u202f: 窄不换行空格
    special_spaces = [u'\xa0', u'\u2002', u'\u2003', u'\u2009', u'\u202f']
    for sp in special_spaces:
        markdown_content = markdown_content.replace(sp, ' ')

    # B. 处理可能遗漏的硬编码 HTML 实体字符串
    markdown_content = markdown_content.replace('&nbsp;', ' ')

    # 3. 合并 3 个及以上的换行符，保持文档整洁
    markdown_content = re.sub(r'\n{3,}', '\n\n', markdown_content)

    # 4. 去除首尾多余的空白
    return markdown_content.strip()