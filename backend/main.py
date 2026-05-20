import models as models
from database import db_dependency, Base, engine
from fastapi import FastAPI
from sqlalchemy import select, func, Numeric, cast


app = FastAPI()
Base.metadata.create_all(bind=engine)

@app.get("/")
def professor():
    return {"Hello": "Buggers"}

@app.post("/professor")
def create_professors(professor: str, db: db_dependency):
    new_professor = models.Professor(name = professor, department = professor)
    db.add(new_professor)
    db.commit()
    db.refresh(new_professor)
    return new_professor

