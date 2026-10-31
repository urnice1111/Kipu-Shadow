import csv
import io
import xml.etree.ElementTree as ET

from app.ingestion.client import Source


def parse_csv(data: bytes, charset: str, separator: str) -> list[dict[str, str]]:
    text = data.decode(charset)
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=separator)
    rows = []
    for line, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(f"fila {line} con más columnas que el encabezado")
        rows.append({k: v if v is not None else "" for k, v in row.items()})
    return rows


def parse_xml(data: bytes) -> list[dict[str, str]]:
    """One row per child of the root: attributes by name, child elements by tag,
    and a child's own attributes as `<tag>_<attr>`."""
    root = ET.fromstring(data)
    rows = []
    for element in root:
        if not isinstance(element.tag, str):
            continue
        row = {k: v for k, v in element.attrib.items()}
        for child in element:
            if not isinstance(child.tag, str):
                continue
            row[child.tag] = (child.text or "").strip()
            for k, v in child.attrib.items():
                row[f"{child.tag}_{k}"] = v
        rows.append(row)
    return rows


def find_key(rows: list[dict[str, str]], expected_keys: set[str]) -> str:
    """The column whose values are unique and all present in record_index for this table."""
    if not rows:
        return ""
    columns = list(rows[0])
    if expected_keys:
        for column in columns:
            values = [r.get(column, "") for r in rows]
            if len(set(values)) == len(values) and all(v in expected_keys for v in values):
                return column
    return columns[0]


def build_table_records(table: str, rows: list[dict[str, str]], expected_keys: set[str]) -> list[dict]:
    key = find_key(rows, expected_keys)
    return [{"id": f"{table}:{row.get(key, '')}", "table": table, "columns": row} for row in rows]


def read_tables(source: Source, index_ids: list[str]) -> list[dict]:
    records = []
    for meta in source.json("/tables"):
        name = meta["name"]
        table = name.rsplit(".", 1)[0]
        data = source.bytes(f"/tables/{name}")
        if meta.get("format") == "xml" or name.endswith(".xml"):
            rows = parse_xml(data)
        else:
            rows = parse_csv(data, meta.get("charset") or "utf-8", meta.get("separator") or ",")
        prefix = f"{table}:"
        expected = {i[len(prefix):] for i in index_ids if i.startswith(prefix)}
        records.extend(build_table_records(table, rows, expected))
    return records
