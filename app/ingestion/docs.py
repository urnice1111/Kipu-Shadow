import re
from pathlib import PurePosixPath

import pymupdf
from bs4 import BeautifulSoup, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag

from app.ingestion.client import Source

FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.M)
PDF_METADATA_KEYS = ("title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate")

SKIP_TAGS = {"style", "script", "title", "meta", "link", "noscript", "template"}
BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "pre", "blockquote", "hr",
    "div", "section", "article", "header", "footer", "main", "nav", "aside",
}
BR = "\u0000"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def parse_front_matter(text: str) -> dict[str, str]:
    """Flat YAML front matter: `key: value`, inline `[a, b]` and `- item` lists become 'a, b'."""
    match = FRONT_MATTER.match(text)
    if not match:
        return {}
    meta: dict[str, str] = {}
    current = None
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and current is not None:
            value = _unquote(item.group(1))
            meta[current] = f"{meta[current]}, {value}" if meta[current] else value
            continue
        if not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            current = key.strip()
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                value = ", ".join(_unquote(v) for v in value[1:-1].split(",") if v.strip())
            meta[current] = _unquote(value)
        elif current is not None:
            meta[current] = f"{meta[current]} {line.strip()}".strip()
    return meta


def _inline(node: Tag) -> str:
    parts = []
    for child in node.children:
        if isinstance(child, Comment):
            parts.append(f"<!--{child}-->")
        elif isinstance(child, (Doctype, Declaration, ProcessingInstruction)):
            continue
        elif isinstance(child, NavigableString):
            parts.append(str(child))
        elif child.name == "br":
            parts.append(BR)
        elif child.name not in SKIP_TAGS:
            parts.append(_inline(child))
    text = re.sub(r"\s+", " ", "".join(parts))
    return re.sub(rf" ?{BR} ?", "\n", text).strip()


def _table(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [_inline(c).replace("|", "\\|").replace("\n", " ") for c in tr.find_all(["th", "td"], recursive=False)]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    lines = []
    for i, row in enumerate(rows):
        lines.append("| " + " | ".join(row + [""] * (width - len(row))) + " |")
        if i == 0:
            lines.append("| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def _has_block(tag: Tag) -> bool:
    return any(d.name in BLOCK_TAGS for d in tag.find_all(True))


def _blocks(node: Tag, out: list[str]) -> None:
    for child in node.children:
        if isinstance(child, Comment):
            out.append(f"<!--{child}-->")
            continue
        if isinstance(child, (Doctype, Declaration, ProcessingInstruction)):
            continue
        if isinstance(child, NavigableString):
            if child.strip():
                out.append(re.sub(r"\s+", " ", str(child)).strip())
            continue
        name = child.name
        if name in SKIP_TAGS:
            continue
        if re.fullmatch(r"h[1-6]", name):
            out.append("#" * int(name[1]) + " " + _inline(child))
        elif name == "p":
            out.append(_inline(child))
        elif name in ("ul", "ol"):
            items = child.find_all("li", recursive=False)
            out.append(
                "\n".join(
                    (f"{i}. " if name == "ol" else "- ") + _inline(li) for i, li in enumerate(items, 1)
                )
            )
        elif name == "table":
            out.append(_table(child))
        elif name == "pre":
            out.append("```\n" + child.get_text().strip("\n") + "\n```")
        elif name == "blockquote":
            inner: list[str] = []
            _blocks(child, inner)
            out.append("\n".join("> " + line for block in inner for line in block.splitlines()))
        elif name == "hr":
            out.append("---")
        elif name in ("html", "head", "body") or _has_block(child):
            _blocks(child, out)
        else:
            out.append(_inline(child))


def html_to_markdown(html: str) -> str:
    out: list[str] = []
    _blocks(BeautifulSoup(html, "lxml"), out)
    return "\n\n".join(b for b in out if b.strip()) + "\n"


def parse_md(text: str, filename: str) -> tuple[str, str, dict[str, str]]:
    meta = parse_front_matter(text)
    heading = HEADING.search(text)
    title = meta.get("title") or (heading.group(1) if heading else "") or PurePosixPath(filename).stem
    return title, text, meta


def parse_html(text: str, filename: str) -> tuple[str, str, dict[str, str]]:
    soup = BeautifulSoup(text, "lxml")
    meta = {}
    for tag in soup.find_all("meta"):
        if tag.get("name") is not None:
            meta[tag["name"]] = tag.get("content", "")
    title = soup.title.get_text(strip=True) if soup.title else ""
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else PurePosixPath(filename).stem
    return title, html_to_markdown(text), meta


def parse_pdf(data: bytes, filename: str) -> tuple[str, str, dict[str, str]]:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        pages = [page.get_text("text").strip() for page in doc]
        info = doc.metadata or {}
    meta = {k: str(info[k]) for k in PDF_METADATA_KEYS if info.get(k)}
    body = "\n\n".join(p for p in pages if p) + "\n"
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    title = meta.get("title") or first_line or PurePosixPath(filename).stem
    return title, body, meta


def build_doc_record(entry: dict, data: bytes) -> dict:
    fmt, filename = entry["format"], entry["filename"]
    if fmt == "pdf":
        title, body, meta = parse_pdf(data, filename)
    elif fmt == "html":
        title, body, meta = parse_html(data.decode("utf-8"), filename)
    elif fmt == "md":
        title, body, meta = parse_md(data.decode("utf-8"), filename)
    else:
        raise ValueError(f"formato de documento desconocido: {fmt}")
    return {
        "id": entry["id"],
        "format": fmt,
        "filename": filename,
        "title": title,
        "body": body,
        "metadata": meta,
    }


def read_docs(source: Source) -> list[dict]:
    return [build_doc_record(entry, source.bytes(f"/docs/{entry['id']}")) for entry in source.json("/docs")]
