from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Annotated
from fastapi import Depends
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("SQL_ALCHEMY_DATABASE_URL")

engine = create_engine(DATABASE_URL)

session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base

def get_db():
    db = session_local()
    try: 
        
        yield db
    finally: 
        db.close()
        
db_dependency = Annotated[
    Session, Depends(get_db)
]