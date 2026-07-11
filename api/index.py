"""Vercel serverless entrypoint.

Vercel's @vercel/python runtime detects the ASGI ``app`` object and serves it.
On Vercel the filesystem is read-only except for ``/tmp`` (ephemeral), so the
SQLite database defaults there. For durable persistence set ``GRE_DB_PATH`` to a
hosted database path / mount, or swap the store for a hosted DB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ephemeral but writable location on Vercel; overridable via env.
os.environ.setdefault("GRE_DB_PATH", "/tmp/gre_app.db")

from webapp.main import app  # noqa: E402  (exposed for the Vercel Python runtime)
