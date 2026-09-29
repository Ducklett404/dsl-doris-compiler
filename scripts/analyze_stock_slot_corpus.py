#!/usr/bin/env python3
"""Read the official stock-slot XLSX corpus without an Excel dependency."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _text(node: ET.Element) -> str:
    return "".join(part.text or "" for part in node.findall(".//m:t", NS))


def read_first_sheet(path: Path) -> list[tuple[str, str, str, str]]:
    with zipfile.ZipFile(path) as book:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            shared = [_text(item) for item in root.findall("m:si", NS)]

        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
        rows: list[tuple[str, str, str, str]] = []
        for row in sheet.findall(".//m:sheetData/m:row", NS):
            values = [""] * 4
            for cell in row.findall("m:c", NS):
                ref = cell.attrib.get("r", "")
                match = re.match(r"([A-Z]+)", ref)
                if not match:
                    continue
                column = 0
                for char in match.group(1):
                    column = column * 26 + ord(char) - 64
                if column > 4:
                    continue
                kind = cell.attrib.get("t")
                if kind == "inlineStr":
                    value = _text(cell)
                else:
                    raw = cell.findtext("m:v", default="", namespaces=NS)
                    value = shared[int(raw)] if kind == "s" and raw else raw
                values[column - 1] = value
            rows.append(tuple(values))
        return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--export-dsl", type=Path)
    args = parser.parse_args()

    rows = read_first_sheet(args.workbook)
    if not rows or rows[0][1:3] != ("query", "slot_dsl"):
        raise SystemExit("unexpected workbook header")
    corpus = [(index + 1, row[2].strip()) for index, row in enumerate(rows[1:], 2) if row[2].strip()]

    functions = Counter(
        name.lower()
        for _, dsl in corpus
        for name in re.findall(r"([A-Za-z_][A-Za-z_0-9]*)\s*\(", dsl)
    )
    patterns = {
        "then": r"\bthen\b",
        "limit": r"\blimit\b",
        "between": r"\bbetween\b",
        "approx": r"~=",
        "cons": r"CONS",
        "exist": r"EXIST",
        "arithmetic": r"\)\s*[+*/-]\s*(?:indicator|rank|queryData)\s*\(",
        "parenthesized_logic": r"^\s*\(|\b(?:and|or)\s*\(",
    }
    result = {
        "worksheetRowsExcludingHeader": len(rows) - 1,
        "effectiveDslRows": len(corpus),
        "blankDslRows": len(rows) - 1 - len(corpus),
        "uniqueDsl": len({dsl for _, dsl in corpus}),
        "maxLength": max(map(lambda item: len(item[1]), corpus), default=0),
        "functions": dict(sorted(functions.items())),
        "features": {
            name: sum(bool(re.search(pattern, dsl, re.IGNORECASE)) for _, dsl in corpus)
            for name, pattern in patterns.items()
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.export_dsl:
        args.export_dsl.parent.mkdir(parents=True, exist_ok=True)
        with args.export_dsl.open("w", encoding="utf-8", newline="\n") as output:
            for row_number, dsl in corpus:
                output.write(json.dumps({"row": row_number, "dsl": dsl}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
