import json
import os

from sqlalchemy import create_engine

from app.env import load_env

load_env()

engine = create_engine(os.environ["DATABASE_URL"])


def json_param(value) -> str | None:
    """`value` as JSON text for a JSONB parameter, with None kept as SQL
    NULL rather than turned into a JSON null."""
    return None if value is None else json.dumps(value)
