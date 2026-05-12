# Changelog

## [Unreleased]

### Added

- **`fetch_web_content` format modes** — Added a new `format` parameter supporting four output modes:
  - `markdown` (default) — Converts cleaned HTML to structured Markdown via `markdownify`, preserving headings, lists, code blocks, tables, and links.
  - `article` — Uses Mozilla Readability to intelligently extract the article body before Markdown conversion. Ideal for blogs, docs, and news sites.
  - `text` — Legacy plain-text extraction behavior for backward compatibility.
  - `outline` — Returns a structural overview (headings hierarchy, semantic regions, interactive element counts) without full content, saving tokens when the agent only needs to understand page layout.

- **Enhanced HTML noise removal** — Content extraction now also strips:
  - Elements with `display:none`, `visibility:hidden`, or `aria-hidden="true"`
  - Inline `style` attributes (semantic noise for LLMs)
  - Empty block-level containers that serve no structural purpose

- **New dependencies** — `markdownify>=0.13.0` and `readability-lxml>=0.8.1` for high-fidelity HTML-to-Markdown conversion and reader-mode extraction.

### Fixed

- **Truncation budget consistency** — `_filter_content_by_prompt` and final truncation now both account for the header length (`URL: ...\nExtraction prompt: ...`), preventing the body text from being silently truncated after filtering.

### Tests

- Added 9 new tests covering all `format` modes:
  - `test_default_is_markdown`
  - `test_text_format_legacy_behavior`
  - `test_markdown_table_preserved`
  - `test_article_format_extracts_body`
  - `test_outline_format`
  - `test_invalid_format`
  - `test_prompt_filter_with_markdown`
  - `test_noise_removal_in_markdown`
  - `test_hidden_elements_removed`

### Changed

- **Proxy defaults** — `USE_PROXY` now defaults to `true` (was `false`), and `PROXY_URL` default port changed to `10809` (was `7890`).
- **Per-engine proxy control** — Added `NO_PROXY_ENGINES` set (`{"baidu", "juejin"}`) so domestic engines skip proxy by default. When `PROXY_ENGINES` is explicitly set, only those engines use proxy; otherwise all engines except domestic ones use proxy.

### Documentation

- Updated `README.md` to describe the new `format` modes and their use cases.
- Updated `CLAUDE.md` with accurate tool signatures and behavior descriptions.
