# manuscript-mcp

Stdio MCP server that converts a manuscript into a structured AST.
Accepts paths or raw text. Markdown + LaTeX paths are pure stdlib
(regex). DOCX path uses pandoc.

## Tools

| Tool | Args | Returns |
|---|---|---|
| `detect_format` | `path: str` | `{path, format}` |
| `extract_sections` | `path_or_text: str`, `fmt: str = "auto"` | section tree |
| `extract_citations` | `path_or_text: str`, `fmt: str = "auto"` | citation list + unique keys |
| `parse_manuscript` | `path_or_text: str`, `fmt: str = "auto"` | full AST |

## Run as stdio MCP

```bash
uv run --with mcp python mcp/manuscript-mcp/server.py
```

## Format autodetect

| Extension | Format |
|---|---|
| `.md`, `.markdown` | markdown |
| `.tex`, `.latex` | latex |
| `.docx` | docx (via pandoc) |
| (other / raw text) | markdown fallback |

Pass `fmt="latex"` etc. to force.

## Citation styles recognized

| Style | Example |
|---|---|
| `latex` | `\cite{key1,key2}`, `\citep`, `\citet`, `\citeauthor` |
| `pandoc` | `[@key]`, `[@key1; @key2]` |
| `numeric` | `[1]`, `[1,2-5]` |
| `author-year` | `(Smith, 2020)`, `(Smith et al., 2020a)` |

## Pandoc dependency

Only `.docx` requires pandoc. If pandoc is missing, requests for
docx return `{"error": "pandoc not on PATH ..."}`. Markdown +
LaTeX paths have no external dependencies.

## Returned shape — `parse_manuscript`

```json
{
  "format": "markdown",
  "word_count": 4123,
  "char_count": 27530,
  "n_sections": 12,
  "n_citations": 47,
  "unique_citation_keys": ["vaswani2017", "kingma2014", "..."],
  "sections": [
    {"level": 1, "title": "Introduction", "span": [0, 16], "kind": "atx-heading"},
    ...
  ],
  "citations": [
    {"key": "vaswani2017", "style": "pandoc", "span": [342, 357]},
    ...
  ]
}
```

## Caller pattern

The `manuscript-ingest` skill already parses citations + references
locally for project-DB persistence. This MCP exposes the same parser
to other agents (e.g. peer-review, reviewer-assistant) so they don't
need to re-implement.
