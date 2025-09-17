from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session

import models, crud, schemas
from database import SessionLocal, engine

models.Base.metadata.create_all(bind=engine)

app = FastAPI()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/processes", response_model=List[schemas.ProcessSchema])
def get_all_processes(db: Session = Depends(get_db)):
    processes = crud.get_processes(db)
    return processes

@app.get("/processes/{process_id}", response_model=schemas.ProcessSchema)
def get_process_by_id(process_id: str, db: Session = Depends(get_db)):
    db_process = crud.get_process_by_id(db = db, id = process_id)
    if db_process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    return db_process

@app.post("/processes", response_model=schemas.ProcessCreateSchema, status_code=201)
def create_new_process(process_data: schemas.ProcessCreateSchema, db: Session = Depends(get_db)):
    return crud.create_process(db = db, process = process_data)

@app.delete("/processes/{process_id}")
def delete_existing_process(process_id: str, db: Session = Depends(get_db)):
    deleted_process = crud.delete_process(db = db, process_id = process_id)
    if deleted_process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    return {"message": "프로세스가 삭제되었습니다."}

@app.put("/processes/{process_id}", response_model=schemas.ProcessCreateSchema)
def update_existing_process(process_id: str, process_data: schemas.ProcessCreateSchema, db: Session = Depends(get_db)):
    updated_process = crud.update_process(db = db, process_id = process_id, process = process_data)
    if updated_process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    return updated_process

