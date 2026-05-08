#!/usr/bin/env python3
"""Update Windows Terminal Modus color scheme JSON files in place.

The script fetches palette data from:
https://protesilaos.com/emacs/modus-themes-colors

It applies the mapping documented in README.adoc and rewrites local JSON files.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


SOURCE_URL = "https://protesilaos.com/emacs/modus-themes-colors"
README_PATH = "README.adoc"

# filename, palette id on source page, scheme display name
TARGET_SCHEMES = [
    (
        "modus-operandi.json",
        "modus-operandi",
        "Modus Operandi"
    ),
    (
        "modus-operandi-tinted.json",
        "modus-operandi-tinted",
        "Modus Operandi Tinted"
    ),
    (
        "modus-operandi-deuteranopia.json",
        "modus-operandi-deuteranopia",
        "Modus Operandi Deuteranopia",
    ),
    (
        "modus-operandi-tritanopia.json",
        "modus-operandi-tritanopia",
        "Modus Operandi Tritanopia",
    ),
    (
        "modus-vivendi.json",
        "modus-vivendi",
        "Modus Vivendi"
    ),
    (
        "modus-vivendi-tinted.json",
        "modus-vivendi-tinted",
        "Modus Vivendi Tinted"
    ),
    (
        "modus-vivendi-deuteranopia.json",
        "modus-vivendi-deuteranopia",
        "Modus Vivendi Deuteranopia",
    ),
    (
        "modus-vivendi-tritanopia.json",
        "modus-vivendi-tritanopia",
        "Modus Vivendi Tritanopia",
    ),
]


def fetch_source(url: str) -> str:
    with urlopen(url) as response:  # nosec B310: trusted HTTPS source
        return response.read().decode("utf-8")


def parse_wt_to_modus_mapping(readme_text: str) -> list[tuple[str, str]]:
    lines = readme_text.splitlines()

    section_start = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == "== color-names mapping ==":
            section_start = idx
            break
    if section_start is None:
        raise ValueError("Could not find 'Color-Names Mapping' section in README.adoc")

    table_start = None
    for idx in range(section_start, len(lines)):
        if lines[idx].strip() == "|===":
            table_start = idx
            break
    if table_start is None:
        raise ValueError("Could not find AsciiDoc mapping table start marker '|===' in README.adoc")

    table_end = None
    for idx in range(table_start + 1, len(lines)):
        if lines[idx].strip() == "|===":
            table_end = idx
            break
    if table_end is None:
        raise ValueError("Could not find AsciiDoc mapping table end marker '|===' in README.adoc")

    cells: list[str] = []
    for line in lines[table_start + 1 : table_end]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        row = stripped[1:]
        for segment in row.split("|"):
            cell = segment.strip()
            if cell:
                cells.append(cell)

    if len(cells) < 4:
        raise ValueError("README mapping table does not contain enough cells")

    if cells[0].lower() == "windows terminal" and cells[1].lower() == "modus":
        cells = cells[2:]

    if len(cells) % 2 != 0:
        raise ValueError("README mapping table has an odd number of cells")

    mapping: list[tuple[str, str]] = []
    for i in range(0, len(cells), 2):
        wt_key = cells[i]
        modus_key = cells[i + 1]
        mapping.append((wt_key, modus_key))
    return mapping


def parse_palettes(page_html: str) -> dict[str, dict[str, str]]:
    # Capture each palette section: heading + table body rows.
    section_re = re.compile(
        r"<h2>\s*(modus-[^<]+?)\s+palette\s*\([^)]*\)\s*</h2>\s*"
        r"<table>.*?<tbody>(.*?)</tbody>.*?</table>",
        re.IGNORECASE | re.DOTALL,
    )
    row_re = re.compile(
        r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>",
        re.IGNORECASE | re.DOTALL,
    )

    palettes: dict[str, dict[str, str]] = {}
    for palette_name, tbody in section_re.findall(page_html):
        entries: dict[str, str] = {}
        for raw_key, raw_value in row_re.findall(tbody):
            key = html.unescape(raw_key).strip()
            value = html.unescape(raw_value).strip()
            if not key:
                continue
            entries[key] = value
        if entries:
            palettes[palette_name.lower()] = entries
    return palettes


def resolve_palette_value(palette: dict[str, str], key: str, stack: set[str] | None = None) -> str:
    if stack is None:
        stack = set()
    if key in stack:
        cycle = " -> ".join([*stack, key])
        raise ValueError(f"Cyclic palette reference: {cycle}")

    if key not in palette:
        raise KeyError(f"Missing palette key '{key}'")

    value = palette[key].strip()
    if value.startswith("#"):
        return value.upper()

    stack.add(key)
    resolved = resolve_palette_value(palette, value, stack)
    stack.remove(key)
    return resolved


def build_scheme(
    palette: dict[str, str],
    scheme_name: str,
    wt_to_modus_key: list[tuple[str, str]],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for wt_key, modus_key in wt_to_modus_key:
        out[wt_key] = resolve_palette_value(palette, modus_key)
    out["name"] = scheme_name
    return out


def update_files(
    root: Path,
    palettes: dict[str, dict[str, str]],
    wt_to_modus_key: list[tuple[str, str]],
) -> list[Path]:
    updated: list[Path] = []
    for filename, palette_id, scheme_name in TARGET_SCHEMES:
        palette = palettes.get(palette_id)
        if palette is None:
            raise KeyError(f"Palette '{palette_id}' was not found in source page")

        target = root / filename
        scheme = build_scheme(palette, scheme_name, wt_to_modus_key)
        target.write_text(json.dumps(scheme, indent=4) + "\n", encoding="utf-8")
        updated.append(target)
    return updated


def main() -> int:
    root = Path(__file__).resolve().parent
    try:
        readme_text = (root / README_PATH).read_text(encoding="utf-8")
        wt_to_modus_key = parse_wt_to_modus_mapping(readme_text)
        source = fetch_source(SOURCE_URL)
        palettes = parse_palettes(source)
        updated_files = update_files(root, palettes, wt_to_modus_key)
    except (URLError, OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    for path in updated_files:
        print(f"Updated {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
