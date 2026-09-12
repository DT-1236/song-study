import os

from dotenv import load_dotenv


def load_env() -> None:
    """Load the repo-root .env into os.environ, leaving any variable that's
    already set untouched."""
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
