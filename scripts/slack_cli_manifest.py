from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    manifest_path = Path(__file__).resolve().parents[1] / ".slack" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
