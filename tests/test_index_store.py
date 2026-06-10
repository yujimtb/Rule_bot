from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rulebot.index_store import INDEX_FILE_NAME, get_search_index


class IndexStoreTest(unittest.TestCase):
    def test_builds_and_reuses_index_when_docs_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            index_dir = root / "index"
            docs.mkdir()
            (docs / "rules.md").write_text("# 鍵について\n鍵を紛失した場合は再発行費用が発生します。\n", encoding="utf-8")

            first = get_search_index(docs, index_dir)
            index_file = index_dir / INDEX_FILE_NAME
            first_mtime = index_file.stat().st_mtime_ns
            second = get_search_index(docs, index_dir)
            second_mtime = index_file.stat().st_mtime_ns

            self.assertEqual(len(first.chunks), 1)
            self.assertEqual(len(second.chunks), 1)
            self.assertEqual(first_mtime, second_mtime)

    def test_rebuilds_index_when_docs_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            index_dir = root / "index"
            docs.mkdir()
            path = docs / "rules.md"
            path.write_text("# 鍵について\n鍵を紛失した場合は再発行費用が発生します。\n", encoding="utf-8")

            get_search_index(docs, index_dir)
            path.write_text("# 消灯\n消灯後は静かにしてください。\n", encoding="utf-8")
            rebuilt = get_search_index(docs, index_dir)

        self.assertIn("消灯", rebuilt.chunks[0].text)


if __name__ == "__main__":
    unittest.main()
