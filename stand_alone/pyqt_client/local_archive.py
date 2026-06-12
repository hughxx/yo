"""Local HTML/Markdown archive for offline collection mode."""
import hashlib
import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


def _app_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


ARCHIVE_DIR = _app_dir() / 'archive'
INDEX_FILE = ARCHIVE_DIR / 'index.json'


def _load_index() -> dict:
    try:
        return json.loads(INDEX_FILE.read_text('utf-8'))
    except Exception:
        return {'emails': {}, 'welink': {}}


def _save_index(index: dict) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2), 'utf-8')


def _safe_name(value: str, fallback: str = 'record') -> str:
    value = (value or '').strip() or fallback
    value = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', value)
    value = re.sub(r'\s+', ' ', value).strip(' .')
    return value[:80] or fallback


def _record_dir(kind: str, name: str, unique_key: str) -> Path:
    day = datetime.now().strftime('%Y%m%d')
    digest = hashlib.md5(unique_key.encode('utf-8', 'ignore')).hexdigest()[:10]
    return ARCHIVE_DIR / kind / day / f'{_safe_name(name)}_{digest}'


class _MarkdownHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.href_stack = []
        self.list_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = tag.lower()
        if tag in ('p', 'div', 'section', 'article', 'header', 'footer', 'tr'):
            self._newline()
        elif tag == 'br':
            self.parts.append('\n')
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._newline()
            self.parts.append('#' * int(tag[1]) + ' ')
        elif tag == 'li':
            self._newline()
            self.parts.append('  ' * max(0, self.list_depth - 1) + '- ')
        elif tag in ('ul', 'ol'):
            self.list_depth += 1
            self._newline()
        elif tag == 'a':
            self.href_stack.append(attrs.get('href', ''))
            self.parts.append('[')
        elif tag == 'img':
            src = attrs.get('src', '')
            alt = attrs.get('alt', '')
            if src:
                self.parts.append(f'![{alt}]({src})')
        elif tag == 'td':
            self.parts.append(' | ')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == 'a':
            href = self.href_stack.pop() if self.href_stack else ''
            self.parts.append(f']({href})' if href else ']')
        elif tag in ('p', 'div', 'section', 'article', 'header', 'footer', 'tr',
                     'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._newline()
        elif tag in ('ul', 'ol'):
            self.list_depth = max(0, self.list_depth - 1)
            self._newline()

    def handle_data(self, data):
        if data:
            self.parts.append(data)

    def _newline(self):
        if self.parts and not self.parts[-1].endswith('\n'):
            self.parts.append('\n')

    def markdown(self) -> str:
        text = ''.join(self.parts)
        text = text.replace('\xa0', ' ').replace('&nbsp;', ' ')
        text = re.sub(r'[ \t]+\n', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


def html_to_markdown(html: str) -> str:
    if not html:
        return ''
    parser = _MarkdownHTMLParser()
    parser.feed(html)
    return parser.markdown()


def _write_record(kind: str, name: str, unique_key: str, html: str,
                  markdown: str, meta: dict) -> dict:
    markdown = markdown if markdown and markdown.strip() else html_to_markdown(html)
    folder = _record_dir(kind, name, unique_key)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'content.html').write_text(html or '', 'utf-8')
    (folder / 'content.md').write_text(markdown or '', 'utf-8')
    (folder / 'meta.json').write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        'utf-8',
    )
    return {
        'Success': True,
        'Message': 'Saved locally',
        'Path': str(folder),
        'HtmlPath': str(folder / 'content.html'),
        'MarkdownPath': str(folder / 'content.md'),
    }


def save_email(payload: dict) -> dict:
    unique_key = payload.get('EmailId') or payload.get('ConversationTopic') or payload.get('Subject') or ''
    name = payload.get('ConversationTopic') or payload.get('Subject') or 'email'
    result = _write_record(
        'email',
        name,
        unique_key,
        payload.get('HtmlBody', ''),
        payload.get('MarkdownBody', ''),
        {
            'type': 'email',
            'saved_at': datetime.now().isoformat(timespec='seconds'),
            'email_id': payload.get('EmailId', ''),
            'conversation_topic': payload.get('ConversationTopic', ''),
            'subject': payload.get('Subject', ''),
            'sender_name': payload.get('SenderName', ''),
            'sender_email': payload.get('SenderEmail', ''),
            'received_time': payload.get('ReceivedTime', ''),
            'matched_rule_name': payload.get('MatchedRuleName', ''),
            'user_id': payload.get('UserId', ''),
            'namespace': payload.get('Namespace', ''),
            'extra_info': payload.get('ExtraInfo', {}),
        },
    )
    index = _load_index()
    topic = (payload.get('ConversationTopic') or '').strip()
    if topic:
        index.setdefault('emails', {})[topic] = {
            'status': 'done',
            'path': result['Path'],
            'saved_at': datetime.now().isoformat(timespec='seconds'),
        }
        _save_index(index)
    return result


def save_welink(payload: dict) -> dict:
    unique_key = payload.get('ChatId') or payload.get('GroupId') or ''
    name = payload.get('GroupName') or payload.get('GroupId') or 'welink'
    result = _write_record(
        'welink',
        name,
        unique_key,
        payload.get('HtmlBody', ''),
        payload.get('MarkdownBody', ''),
        {
            'type': 'welink',
            'saved_at': datetime.now().isoformat(timespec='seconds'),
            'chat_id': payload.get('ChatId', ''),
            'group_id': payload.get('GroupId', ''),
            'group_name': payload.get('GroupName', ''),
            'start_time': payload.get('StartTime', ''),
            'end_time': payload.get('EndTime', ''),
            'upload_by': payload.get('UploadBy', ''),
            'is_daily': bool(payload.get('IsDaily', False)),
        },
    )
    index = _load_index()
    chat_id = (payload.get('ChatId') or '').strip()
    duplicate = False
    if chat_id:
        duplicate = chat_id in index.setdefault('welink', {})
        index['welink'][chat_id] = {
            'path': result['Path'],
            'saved_at': datetime.now().isoformat(timespec='seconds'),
        }
        _save_index(index)
    result['Duplicate'] = duplicate
    return result


def parse_status(topics: list) -> dict:
    index = _load_index()
    emails = index.get('emails', {})
    return {
        topic: emails.get(topic, {}).get('status', '')
        for topic in topics
        if emails.get(topic, {}).get('status')
    }


def public_url_from_upload(upload_url: str, public_base: str, object_id: str, filename: str) -> str:
    if public_base:
        return f'{public_base.rstrip("/")}/rag_pic/{object_id}/{filename}'
    parsed = urlparse(upload_url)
    base = f'{parsed.scheme}://{parsed.netloc}'
    return f'{base}/rag_pic/{object_id}/{filename}'
