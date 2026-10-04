"""List a public Google Drive folder and download its Google Sheets as .xlsx.

    python -m pipeline.parsers.tools.g3_fetch_drive_folder <folder_id> <out_dir> [name_regex]

The folder page (https://drive.google.com/drive/folders/<id>) embeds the listing as
JS-escaped JSON: ``"<file id>",["<folder id>"],"<name>","<mime type>"``. Each spreadsheet
whose name matches ``name_regex`` is exported with
https://docs.google.com/spreadsheets/d/<id>/export?format=xlsx and saved as
``<out_dir>/<name>.xlsx``; ``<out_dir>/listing.json`` records names, ids and mime types.
Used for LOST 2021's scoresheet folder (linked from the Stanford tournament list).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def listing(folder_id: str) -> list[dict[str, str]]:
    r = requests.get(f"https://drive.google.com/drive/folders/{folder_id}", headers=UA, timeout=60)
    r.raise_for_status()
    s = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), r.text).replace("\\/", "/")
    items = re.findall(r'"([-\w]{25,60})",\["' + re.escape(folder_id) + r'"\],"([^"]*)","([^"]+)"', s)
    return [{"id": i, "name": n, "mime": m} for i, n, m in items]


def main(argv: list[str]) -> int:
    folder, out = argv[0], Path(argv[1])
    rx = re.compile(argv[2]) if len(argv) > 2 else None
    out.mkdir(parents=True, exist_ok=True)
    items = listing(folder)
    (out / "listing.json").write_text(json.dumps({"folder_id": folder, "items": items}, indent=1))
    for it in items:
        if it["mime"] != "application/vnd.google-apps.spreadsheet":
            continue
        if rx and not rx.search(it["name"]):
            continue
        url = f"https://docs.google.com/spreadsheets/d/{it['id']}/export?format=xlsx"
        r = requests.get(url, headers=UA, timeout=60)
        ok = r.status_code == 200 and "spreadsheetml" in r.headers.get("content-type", "")
        if ok:
            (out / f"{it['name']}.xlsx").write_bytes(r.content)
        print(("ok  " if ok else "FAIL"), it["name"], len(r.content))
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
