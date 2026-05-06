import models as models
from database import db_dependency, Base, engine
from fastapi import FastAPI
from sqlalchemy import select, func, Numeric, cast


app = FastAPI()
Base.metadata.create_all(bind=engine)

@app.get("/")
def professor():
    return {"Hello": "Buggers"}

