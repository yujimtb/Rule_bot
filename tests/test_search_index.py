from __future__ import annotations

import unittest

from rulebot.document_store import DocumentChunk
from rulebot.search_index import SearchIndex


class SearchIndexTest(unittest.TestCase):
    def test_planned_terms_find_semantically_related_chunk(self) -> None:
        index = SearchIndex.from_chunks(
            [
                DocumentChunk(source="rules.md", location="鍵について", text="鍵を紛失した場合は再発行費用が発生します。"),
                DocumentChunk(source="rules.md", location="食器", text="食器を割った場合はスタッフへ報告してください。"),
            ]
        )

        hits = index.search(["キーをなくした場合は？", "鍵 紛失 再発行"], top_k=5)

        self.assertTrue(hits)
        self.assertEqual(hits[0].chunk.location, "鍵について")

    def test_limits_results_to_top_k(self) -> None:
        index = SearchIndex.from_chunks(
            [
                DocumentChunk(source="rules.md", location="one", text="消灯後は静かにしてください。"),
                DocumentChunk(source="rules.md", location="two", text="消灯時間を守ってください。"),
            ]
        )

        hits = index.search(["消灯"], top_k=1)

        self.assertEqual(len(hits), 1)


if __name__ == "__main__":
    unittest.main()
