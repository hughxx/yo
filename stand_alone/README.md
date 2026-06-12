# Offline standalone client

This standalone mode stops at local `html` and `markdown` files.

Generated records are written under:

```text
stand_alone/pyqt_client/archive/
```

Each record folder contains:

- `content.html`
- `content.md`
- `meta.json`

Offline behavior:

- Email and WeLink collection saves HTML and Markdown locally.
- Email rules and WeLink rules are stored in local JSON files.
- No OCR, LLM summarization, experience extraction, or experience-engine upload is run for collected records.
- Image-to-public-link is still available if `File server URL` and `Image public base` are configured.
- Auto reply can call a locally configured OpenAI-compatible LLM using `LLM base URL`, `LLM API key`, and `LLM model`.

Run from this directory with:

```bat
run_offline_client.bat
```
