import json
import re
from pathlib import Path
from typing import Dict, List

from pypdf import PdfReader

PDF_PATH = Path("Channel Mapping.pdf")
OUTPUT_PATH = Path("channel_mapping.json")

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def extract_entries() -> Dict[str, Dict[str, str]]:
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"Missing PDF: {PDF_PATH}")

    reader = PdfReader(str(PDF_PATH))
    entries: Dict[str, Dict[str, str]] = {}
    issues: List[str] = []

    for page_idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        i = 0
        while i < len(lines):
            line = lines[i]
            tokens = line.split()
            uuid_idx = next((idx for idx, token in enumerate(tokens) if UUID_RE.fullmatch(token)), None)

            if uuid_idx is None:
                i += 1
                continue

            channel_name = " ".join(tokens[:uuid_idx]).strip()
            channel_id = tokens[uuid_idx]

            group_title = ""
            region = ""
            if i + 1 < len(lines):
                group_line_tokens = lines[i + 1].split()
                if len(group_line_tokens) >= 2:
                    region = group_line_tokens[-1]
                    group_title = " ".join(group_line_tokens[:-1])
                elif group_line_tokens:
                    group_title = group_line_tokens[0]

            if not channel_name:
                channel_name = f"UNKNOWN_{channel_id}"

            entries[channel_id] = {
                "title": channel_name,
                "group_title": group_title,
                "region": region,
            }

            i += 2

    if issues:
        print("Warnings during extraction:")
        for msg in issues:
            print(f"- {msg}")

    return entries


def main() -> None:
    entries = extract_entries()
    sorted_items = sorted(entries.items(), key=lambda kv: kv[1]["title"].lower())
    ordered = {cid: data for cid, data in sorted_items}

    OUTPUT_PATH.write_text(json.dumps(ordered, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Extracted {len(entries)} channel mappings -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
