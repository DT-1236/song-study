import os

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

engine = create_engine(os.environ["DATABASE_URL"])
