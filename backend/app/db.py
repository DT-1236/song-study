import os

from dotenv import load_dotenv
from sqlalchemy import create_engine


def load_env() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


load_env()

engine = create_engine(os.environ["DATABASE_URL"])
