"""Miskatonic Server: Flask application factory and local archive routes."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.datastructures import ImmutableMultiDict
from werkzeug.exceptions import RequestEntityTooLarge

from .database import (
    close_db,
    count_entries,
    create_entry,
    delete_entry,
    get_entry,
    get_db,
    init_db,
    list_entries,
    update_entry,
)

MAX_QUERY_LENGTH = 100
INDEX_RESULT_LIMIT = 100
CATEGORIES = (
    "Artifact",
    "Investigation",
    "Dream",
    "Correspondence",
    "Field Note",
)


class EntryFormValues(TypedDict):
    title: str
    category: str
    content: str
    sanity: int


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    default_database = (
        os.environ.get("MISKATONIC_DATABASE")
        or str(Path(__file__).resolve().parents[1] / "instance" / "miskatonic.sqlite3")
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("MISKATONIC_SECRET_KEY") or secrets.token_hex(32),
        DATABASE=default_database,
        MAX_CONTENT_LENGTH=128 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_env_flag("MISKATONIC_COOKIE_SECURE"),
        SESSION_COOKIE_NAME="miskatonic_session",
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)
    init_db(app)

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": csrf_token}

    @app.after_request
    def security_headers(response):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=(), payment=()",
        )
        # Static assets may be cached; archive pages and exports are private data.
        if request.endpoint == "static":
            response.headers["Cache-Control"] = "public, max-age=86400"
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error):
        return render_template("error.html", code=413, message="This request is too large."), 413

    @app.get("/")
    def index():
        search = request.args.get("q", "").strip()
        if len(search) > MAX_QUERY_LENGTH:
            abort(400, description=f"Search must be {MAX_QUERY_LENGTH} characters or fewer.")
        entries = list_entries(search, limit=INDEX_RESULT_LIMIT)
        total = count_entries(search)
        return render_template(
            "index.html",
            entries=entries,
            search=search,
            total_entries=total,
        )

    @app.get("/export")
    def export_archive():
        """Download the whole archive as a portable JSON document."""
        entries = list_entries(limit=None)
        now = datetime.now(timezone.utc)
        payload = {
            "project": "Miskatonic Server",
            "exported_at": now.isoformat(timespec="seconds"),
            "count": len(entries),
            "entries": [entry.as_dict() for entry in entries],
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        response = Response(body, mimetype="application/json")
        response.headers["Content-Disposition"] = (
            f'attachment; filename="miskatonic-archive-{now:%Y%m%d}.json"'
        )
        return response

    @app.route("/entries/new", methods=("GET", "POST"))
    def new_entry():
        if request.method == "POST":
            _require_csrf()
            values, errors = _validate_form(request.form)
            if errors:
                return render_template(
                    "entry_form.html",
                    entry=values,
                    errors=errors,
                    categories=CATEGORIES,
                    is_edit=False,
                ), 400
            try:
                entry_id = create_entry(**values)
            except sqlite3.Error:
                app.logger.exception("Failed to create archive entry.")
                abort(500, description="The archive could not save this entry.")
            flash("The entry was added to the archive.", "success")
            return redirect(url_for("entry_detail", entry_id=entry_id), code=303)

        return render_template(
            "entry_form.html",
            entry={"title": "", "category": CATEGORIES[0], "content": "", "sanity": 100},
            errors=[],
            categories=CATEGORIES,
            is_edit=False,
        )

    @app.get("/entries/<int:entry_id>")
    def entry_detail(entry_id: int):
        entry = get_entry(entry_id)
        if entry is None:
            abort(404)
        return render_template("entry_detail.html", entry=entry)

    @app.route("/entries/<int:entry_id>/edit", methods=("GET", "POST"))
    def edit_entry(entry_id: int):
        entry = get_entry(entry_id)
        if entry is None:
            abort(404)
        if request.method == "POST":
            _require_csrf()
            values, errors = _validate_form(request.form)
            if errors:
                return render_template(
                    "entry_form.html",
                    entry={**values, "id": entry_id},
                    errors=errors,
                    categories=CATEGORIES,
                    is_edit=True,
                ), 400
            try:
                updated = update_entry(entry_id, **values)
            except sqlite3.Error:
                app.logger.exception("Failed to update archive entry %s.", entry_id)
                abort(500, description="The archive could not update this entry.")
            if not updated:
                abort(404)
            flash("The archive entry was updated.", "success")
            return redirect(url_for("entry_detail", entry_id=entry_id), code=303)

        return render_template(
            "entry_form.html",
            entry=entry,
            errors=[],
            categories=CATEGORIES,
            is_edit=True,
        )

    @app.post("/entries/<int:entry_id>/delete")
    def remove_entry(entry_id: int):
        _require_csrf()
        try:
            deleted = delete_entry(entry_id)
        except sqlite3.Error:
            app.logger.exception("Failed to delete archive entry %s.", entry_id)
            abort(500, description="The archive could not delete this entry.")
        if not deleted:
            abort(404)
        flash("The entry was removed from the archive.", "success")
        return redirect(url_for("index"), code=303)

    @app.get("/health")
    def health():
        try:
            get_db().execute("SELECT 1").fetchone()
        except sqlite3.Error:
            app.logger.exception("Archive health check failed.")
            abort(503, description="The archive database is unavailable.")
        return {"status": "ok"}

    @app.errorhandler(400)
    @app.errorhandler(405)
    @app.errorhandler(404)
    @app.errorhandler(500)
    @app.errorhandler(503)
    def http_error(error):
        description = getattr(error, "description", "The request could not be completed.")
        return render_template(
            "error.html",
            code=error.code,
            message=description,
        ), error.code

    return app


def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_csrf() -> None:
    expected = session.get("_csrf_token", "")
    supplied = request.form.get("_csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, description="The form expired or failed its security check. Please try again.")


def _validate_form(form: ImmutableMultiDict[str, str]) -> tuple[EntryFormValues, list[str]]:
    title = form.get("title", "").strip()
    category = form.get("category", "").strip()
    content = form.get("content", "").strip()
    raw_sanity = form.get("sanity", "")
    errors: list[str] = []

    if not title:
        errors.append("A title is required.")
    elif len(title) > 120:
        errors.append("The title must be 120 characters or fewer.")
    if category not in CATEGORIES:
        errors.append("Choose a category from the list.")
    if not content:
        errors.append("An entry is required.")
    elif len(content) > 10_000:
        errors.append("The entry must be 10,000 characters or fewer.")
    try:
        sanity = int(raw_sanity)
        if not 0 <= sanity <= 100:
            raise ValueError
    except (TypeError, ValueError):
        sanity = 100
        errors.append("Sanity must be a whole number from 0 to 100.")

    return {
        "title": title,
        "category": category,
        "content": content,
        "sanity": sanity,
    }, errors


def main() -> None:
    """Run a loopback-only development server."""
    app = create_app()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)


if __name__ == "__main__":
    main()
