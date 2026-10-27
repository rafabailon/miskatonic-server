# Miskatonic Server

A small, responsive Flask application for cataloguing strange artifacts, investigations, dreams, correspondence, and field notes. Entries are stored in a local SQLite database; the interface is inspired by the restricted collections of Miskatonic University.

The project and Python distribution are named **Miskatonic Server**; the archive interface keeps the in-universe name *Miskatonic Special Collections*.

## Features

- Create, read, update, and delete archive entries.
- Search titles and categories, with literal handling of SQL wildcard characters.
- Record type, field notes, timestamps, and a sanity index from 0 to 100.
- Accurate record counts and a clear notice when the archive view is truncated at 100 results.
- Download the whole archive as portable, UTF-8 JSON from `/export` or the **Export** navigation link.
- Responsive archive, detail, and form pages with keyboard skip navigation.
- SQLite persistence with WAL journaling, parameterized queries, bounded inputs, and database constraints.
- Session-bound CSRF tokens for every mutation form.
- Escaped Jinja templates, request-size limits, strict security headers, and a loopback-only default server.
- Fully local CSS and JavaScript; no CSS framework CDN is required.
- Automated route, repository, validation, persistence, security, export, and boundary tests.

## Requirements and setup

- Python 3.10 or newer
- Flask 3.1 or newer (`requirements.txt` / `pyproject.toml`)

Create an environment and install the runtime dependency:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

For an installed `miskatonic-server` command, install the project itself instead:

```sh
python -m pip install -e .
miskatonic-server
```

Start the local server from a source checkout:

```sh
make run
```

Open `http://127.0.0.1:5000`. The first run creates `instance/miskatonic.sqlite3` and its schema automatically. The application binds to `127.0.0.1`; it is a personal local archive, not a multi-user service.

### Configuration

| Variable | Purpose |
| --- | --- |
| `MISKATONIC_SECRET_KEY` | Stable session-signing key. If unset, a random key is generated at startup and sessions do not survive restarts. |
| `MISKATONIC_DATABASE` | Optional SQLite database path. Defaults to `instance/miskatonic.sqlite3`. |
| `MISKATONIC_COOKIE_SECURE` | Set to `1`, `true`, `yes`, or `on` behind HTTPS to mark the session cookie secure. |
| `PORT` | Development-server port. Defaults to `5000`. |

Example:

```sh
export MISKATONIC_SECRET_KEY="replace-with-a-long-random-value"
```

The site loads Google Fonts from an external CDN, so the preferred typography needs an internet connection. The local stylesheet and system font fallbacks keep the page usable offline. For a deployment behind HTTPS, configure secure session cookies and use an appropriate production WSGI server; do not expose Flask's development server to a public network.

## Archive routes

| Route | Purpose |
| --- | --- |
| `/` | Search and browse up to 100 recent records, with a total matching count |
| `/entries/new` | Create an entry |
| `/entries/<id>` | Read an entry |
| `/entries/<id>/edit` | Update an entry |
| `/entries/<id>/delete` | Delete an entry using a CSRF-protected POST |
| `/export` | Download every entry as a JSON attachment |
| `/health` | Check that the application can query SQLite |

Accepted categories are Artifact, Investigation, Dream, Correspondence, and Field Note. Titles are limited to 120 characters, categories to the fixed list, and field notes to 10,000 characters. Search terms are limited to 100 characters. The HTTP request-body cap accounts for URL-encoded Unicode at the maximum note length.

The export is a snapshot of the archive data, not a copy of the SQLite file:

```json
{
  "project": "Miskatonic Server",
  "exported_at": "2026-10-23T12:00:00+00:00",
  "count": 1,
  "entries": [
    {
      "id": 1,
      "title": "The Whispering Stone",
      "category": "Artifact",
      "content": "Recovered from the northern shore.",
      "sanity": 72,
      "created_at": "2026-10-23T11:58:04+00:00",
      "updated_at": "2026-10-23T11:58:04+00:00"
    }
  ]
}
```

## Tests and performance

Run the automated suite:

```sh
make test
```

Run compilation and the full suite together:

```sh
make check
```

Run the local SQLite and rendered-search benchmark:

```sh
make benchmark
```

The benchmark inserts 1,000 synthetic local records and reports timing for 100 archive-search requests. Measurements are informational and vary with the machine and Python/SQLite versions; they are not a throughput guarantee. Tests use temporary databases and do not alter the personal archive.

## Project structure

```text
src/
  __init__.py            Package marker for the Miskatonic Server application
  app.py                 Flask factory, routes, validation, export, and request protections
  database.py            SQLite schema, connection tuning, and parameterized archive operations
  templates/             Shared layout, archive, forms, detail, and error pages
  static/css/site.css    Responsive local styling
  static/favicon.svg     Matching archive icon
  static/js/form.js      Sanity-slider and delete-confirmation enhancement
tests/
  test_app.py            Route, CRUD, validation, security, caching, and export tests
  test_database.py       WAL, search, count, limit, update, and delete repository tests
  run_benchmarks.py      Reproducible local microbenchmark
pyproject.toml           Package metadata and the miskatonic-server entry point
Makefile                 install, run, test, check, benchmark, and clean targets
instance/                Generated local database (not committed)
```

## Cleaning up

Remove generated Python caches and build artifacts without touching the archive:

```sh
make clean
```

The SQLite database lives only in `instance/` and is intentionally ignored by Git. Use the JSON export if you want a human-readable copy.
