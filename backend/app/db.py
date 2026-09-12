import os

from sqlalchemy import create_engine

from app.env import load_env

load_env()

engine = create_engine(os.environ["DATABASE_URL"])
