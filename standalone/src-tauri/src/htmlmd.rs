//! HTML → Markdown（Rust 核心层，DESIGN.md §5.3）。
//! 用 htmd 转换，再做与旧 html2text 一致的后处理。

use regex::Regex;

pub fn html_to_md(html: &str) -> String {
    if html.trim().is_empty() {
        return String::new();
    }
    let md = htmd::convert(html).unwrap_or_default();
    post_process(&md)
}

fn post_process(md: &str) -> String {
    let mut s = md.to_string();

    // 1) 去掉无效空图片占位 ![]()
    let empty_img = Regex::new(r"!\[\]\(\)").unwrap();
    s = empty_img.replace_all(&s, "").into_owned();

    // 2) 各种特殊空格归一化为普通空格
    //    \u{a0} NBSP, \u{2002} En, \u{2003} Em, \u{2009} Thin, \u{202f} Narrow NBSP
    for sp in ['\u{a0}', '\u{2002}', '\u{2003}', '\u{2009}', '\u{202f}'] {
        s = s.replace(sp, " ");
    }
    s = s.replace("&nbsp;", " ");

    // 3) 无序列表符号统一为 '-'（htmd 输出 '*   '，对齐旧 html2text）
    let bullet = Regex::new(r"(?m)^(\s*)\*(\s+)").unwrap();
    s = bullet.replace_all(&s, "$1-$2").into_owned();

    // 4) 合并 3+ 连续换行
    let many_nl = Regex::new(r"\n{3,}").unwrap();
    s = many_nl.replace_all(&s, "\n\n").into_owned();

    // 4) 去首尾空白
    s.trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn basic_conversion() {
        let html = r#"<html><body>
            <h1>标题</h1>
            <p>这是&nbsp;一段&nbsp;正文，含<a href="https://example.com">链接</a>。</p>
            <ul><li>项一</li><li>项二</li></ul>
            <img src="" alt="">
        </body></html>"#;
        let md = html_to_md(html);
        assert!(md.contains("标题"), "应保留标题文本: {md}");
        assert!(md.contains("链接") && md.contains("https://example.com"), "应保留链接: {md}");
        assert!(md.contains("项一") && md.contains("项二"), "应保留列表: {md}");
        assert!(!md.contains("&nbsp;"), "应清理 &nbsp;: {md}");
        assert!(!md.contains("![]()"), "应去掉空图片占位: {md}");
        assert!(!md.contains("\n\n\n"), "不应有 3+ 连续换行: {md}");
    }

    #[test]
    fn empty_input() {
        assert_eq!(html_to_md(""), "");
        assert_eq!(html_to_md("   "), "");
    }
}
