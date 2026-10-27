"""Repository-level tests for the Miskatonic Server SQLite layer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.app import create_app
from src.database import (
    count_entries,
    create_entry,
    delete_entry,
    get_db,
    get_entry,
    list_entries,
    update_entry,
)


class ArchiveRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp_dir.name) / "repository.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "repository-test-secret",
                "DATABASE": self.database,
            }
        )
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self) -> None:
        self.context.pop()
        self.temp_dir.cleanup()

    def add_entry(self, title: str, category: str = "Artifact") -> int:
        return create_entry(
            title=title,
            category=category,
            content=f"Notes for {title}.",
            sanity=50,
        )

    def test_wal_mode_and_connection_pragmas_are_enabled(self) -> None:
        connection = get_db()
        self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 5000)

    def test_list_entries_validates_limits_and_supports_unbounded_exports(self) -> None:
        for index in range(3):
            self.add_entry(f"Record {index}")

        self.assertEqual(len(list_entries(limit=1)), 1)
        self.assertEqual(len(list_entries(limit=None)), 3)
        self.assertEqual(len(list_entries(limit=200)), 3)
        for invalid_limit in (0, -1, 201):
            with self.subTest(limit=invalid_limit):
                with self.assertRaises(ValueError):
                    list_entries(limit=invalid_limit)

    def test_count_entries_matches_the_search_filter(self) -> None:
        self.add_entry("Brass Key", category="Artifact")
        self.add_entry("Brass Bell", category="Artifact")
        self.add_entry("A Dream", category="Dream")

        self.assertEqual(count_entries(), 3)
        self.assertEqual(count_entries("brass"), 2)
        self.assertEqual(count_entries("Dream"), 1)
        self.assertEqual(count_entries("missing"), 0)

    def test_search_treats_percent_and_underscore_as_literals(self) -> None:
        percent_id = self.add_entry("A 100% Certainty")
        self.add_entry("A 1000 Certainty")
        underscore_id = self.add_entry("file_name")
        self.add_entry("fileName")

        self.assertEqual([entry.id for entry in list_entries("100%")], [percent_id])
        self.assertEqual([entry.id for entry in list_entries("file_")], [underscore_id])

    def test_unbounded_listing_is_ordered_by_most_recent_update(self) -> None:
        first = self.add_entry("First")
        second = self.add_entry("Second")
        third = self.add_entry("Third")

        self.assertEqual([entry.id for entry in list_entries(limit=None)], [third, second, first])

    def test_update_and_delete_report_missing_records(self) -> None:
        entry_id = self.add_entry("Original")

        self.assertTrue(update_entry(entry_id, "Revised", "Dream", "Changed.", 10))
        updated = get_entry(entry_id)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual((updated.title, updated.category, updated.sanity), ("Revised", "Dream", 10))

        self.assertTrue(delete_entry(entry_id))
        self.assertIsNone(get_entry(entry_id))
        self.assertFalse(update_entry(entry_id, "Missing", "Dream", "No record.", 10))
        self.assertFalse(delete_entry(entry_id))

    def test_entry_as_dict_contains_export_fields(self) -> None:
        entry_id = self.add_entry("Exported")
        entry = get_entry(entry_id)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(
            set(entry.as_dict()),
            {"id", "title", "category", "content", "sanity", "created_at", "updated_at"},
        )
        self.assertEqual(entry.as_dict()["title"], "Exported")


if __name__ == "__main__":
    unittest.main()
