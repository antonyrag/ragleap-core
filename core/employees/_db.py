"""Shared DB connection helper — same DATABASE_URL convention as core/retrieval.py."""
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ragleap:ragleap@localhost:5432/ragleap_core"
)


def get_connection():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)
