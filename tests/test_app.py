"""End-to-end route tests for Miskatonic Server."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app import CATEGORIES, create_app


class ArchiveAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp_dir.name) / "test.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "DATABASE": self.database,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def csrf_token(self, path: str = "/entries/new") -> str:
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(rb'name="_csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def valid_form(self, **overrides: str) -> dict[str, str]:
        return {
            "_csrf_token": self.csrf_token(),
            "title": "The Whispering Stone",
            "category": CATEGORIES[0],
            "content": "Recovered from the northern shore.",
            "sanity": "72",
            **overrides,
        }

    def create_entry(self, **overrides: str) -> int:
        response = self.client.post(
            "/entries/new",
            data=self.valid_form(**overrides),
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        return int(response.headers["Location"].rsplit("/", 1)[-1])

    def test_create_read_update_and_delete_entry(self) -> None:
        entry_id = self.create_entry()
        detail = self.client.get(f"/entries/{entry_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"The Whispering Stone", detail.data)
        self.assertIn(b"Recovered from the northern shore.", detail.data)
        self.assertIn(b'data-confirm="Remove this record from the local archive?"', detail.data)
        self.assertIn(b"/static/js/form.js", detail.data)

        update = self.client.post(
            f"/entries/{entry_id}/edit",
            data=self.valid_form(title="The Recovered Stone", sanity="0"),
        )
        self.assertEqual(update.status_code, 303)
        self.assertIn(b"The Recovered Stone", self.client.get(f"/entries/{entry_id}").data)

        deletion = self.client.post(
            f"/entries/{entry_id}/delete",
            data={"_csrf_token": self.csrf_token(f"/entries/{entry_id}")},
        )
        self.assertEqual(deletion.status_code, 303)
        self.assertEqual(self.client.get(f"/entries/{entry_id}").status_code, 404)

    def test_validation_enforces_field_boundaries(self) -> None:
        cases = (
            ({"title": " "}, b"A title is required."),
            ({"title": "t" * 121}, b"120 characters or fewer"),
            ({"category": "Unknown"}, b"Choose a category"),
            ({"content": " "}, b"An entry is required."),
            ({"content": "c" * 10_001}, b"10,000 characters or fewer"),
            ({"sanity": "-1"}, b"whole number from 0 to 100"),
            ({"sanity": "101"}, b"whole number from 0 to 100"),
            ({"sanity": "72.5"}, b"whole number from 0 to 100"),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                response = self.client.post("/entries/new", data=self.valid_form(**overrides))
                self.assertEqual(response.status_code, 400)
                self.assertIn(expected, response.data)

    def test_maximum_valid_field_sizes_and_sanity_edges_are_accepted(self) -> None:
        for sanity in ("0", "100"):
            with self.subTest(sanity=sanity):
                response = self.client.post(
                    "/entries/new",
                    data=self.valid_form(title="t" * 120, content="x" * 10_000, sanity=sanity),
                )
                self.assertEqual(response.status_code, 303)

        unicode_boundary = self.client.post(
            "/entries/new",
            data=self.valid_form(content="🜂" * 10_000),
        )
        self.assertEqual(unicode_boundary.status_code, 303)

    def test_mutations_require_a_session_bound_csrf_token(self) -> None:
        self.assertEqual(
            self.client.post(
                "/entries/new",
                data={
                    "title": "Forged",
                    "category": CATEGORIES[0],
                    "content": "No token",
                    "sanity": "50",
                },
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post("/entries/1/delete", data={"_csrf_token": "incorrect"}).status_code,
            400,
        )

    def test_output_escapes_untrusted_html(self) -> None:
        entry_id = self.create_entry(
            title="<script>alert(1)</script>",
            content="<img src=x onerror=alert(1)>",
        )
        response = self.client.get(f"/entries/{entry_id}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<script>alert(1)</script>", response.data)
        self.assertIn(b"&lt;script&gt;", response.data)
        self.assertIn(b"&lt;img src=x", response.data)

    def test_search_treats_wildcards_as_literals_and_is_case_insensitive(self) -> None:
        self.create_entry(title="A 100% Certain Discovery")
        self.create_entry(title="An Unrelated Discovery")
        filtered = self.client.get("/?q=100%25")
        self.assertIn(b"A 100% Certain Discovery", filtered.data)
        self.assertNotIn(b"An Unrelated Discovery", filtered.data)
        self.assertIn(b"1 record", filtered.data)
        self.assertIn(b"A 100% Certain Discovery", self.client.get("/?q=cErTaIn").data)

    def test_archive_count_reports_total_matching_records(self) -> None:
        self.create_entry(title="First record")
        self.create_entry(title="Second record")
        response = self.client.get("/")
        self.assertIn(b"2 records", response.data)
        self.assertEqual(self.client.get("/?q=First").get_data(as_text=True).count("1 record"), 1)

    def test_export_returns_every_entry_as_portable_json(self) -> None:
        first_id = self.create_entry(title="The Brass Key", content="Cold to the touch.")
        second_id = self.create_entry(
            title="Sigilo ✦",
            category=CATEGORIES[1],
            content="Notas de campo.",
            sanity="0",
        )
        response = self.client.get("/export")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn("miskatonic-archive-", response.headers["Content-Disposition"])

        payload = response.get_json()
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["project"], "Miskatonic Server")
        self.assertEqual(payload["count"], 2)
        self.assertEqual({entry["id"] for entry in payload["entries"]}, {first_id, second_id})
        self.assertIn("Sigilo ✦", {entry["title"] for entry in payload["entries"]})

    def test_export_of_an_empty_archive_is_valid_json(self) -> None:
        payload = self.client.get("/export").get_json()
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["entries"], [])

    def test_unknown_entry_and_oversized_search_are_rejected(self) -> None:
        self.assertEqual(self.client.get("/entries/999").status_code, 404)
        self.assertEqual(self.client.get("/?q=" + "x" * 101).status_code, 400)
        self.assertEqual(self.client.get("/entries/1/delete").status_code, 405)

    def test_large_request_is_rejected_with_clear_response(self) -> None:
        response = self.client.post("/entries/new", data={"padding": "x" * (128 * 1024 + 1)})
        self.assertEqual(response.status_code, 413)
        self.assertIn(b"This request is too large.", response.data)

    def test_security_headers_and_health_check(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("camera=()", response.headers["Permissions-Policy"])
        policy = response.headers["Content-Security-Policy"]
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertNotIn("cdn.tailwindcss.com", policy)
        script_policy = next(part for part in policy.split(";") if part.strip().startswith("script-src"))
        self.assertNotIn("'unsafe-inline'", script_policy)
        self.assertNotIn("'unsafe-eval'", script_policy)
        self.assertTrue(self.app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual(self.app.config["SESSION_COOKIE_SAMESITE"], "Lax")
        self.assertEqual(self.app.config["SESSION_COOKIE_NAME"], "miskatonic_session")

    def test_static_assets_are_cacheable_while_archive_pages_are_private(self) -> None:
        page = self.client.get("/")
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        asset = self.client.get("/static/css/site.css")
        try:
            self.assertIn("max-age=86400", asset.headers["Cache-Control"])
        finally:
            asset.close()

    def test_static_archive_assets_are_available(self) -> None:
        for path in ("/static/favicon.svg", "/static/css/site.css", "/static/js/form.js"):
            with self.subTest(path=path):
                response = self.client.get(path)
                try:
                    self.assertEqual(response.status_code, 200)
                finally:
                    response.close()

    def test_default_database_is_in_project_instance_directory(self) -> None:
        with patch("src.app.init_db"):
            app = create_app({"TESTING": True, "SECRET_KEY": "test-session-secret"})
        expected = Path(__file__).resolve().parents[1] / "instance" / "miskatonic.sqlite3"
        self.assertEqual(Path(app.config["DATABASE"]), expected)

    def test_database_persists_between_application_instances(self) -> None:
        self.create_entry()
        second_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "second-test-secret",
                "DATABASE": self.database,
            }
        )
        with second_app.test_client() as client:
            self.assertIn(b"The Whispering Stone", client.get("/").data)


if __name__ == "__main__":
    unittest.main()
