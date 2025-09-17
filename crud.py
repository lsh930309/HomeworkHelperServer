from sqlalchemy.orm import Session
import models
import schemas
import uuid

def get_processes(db: Session):
    return db.query(models.Process).all()

def get_process_by_id(db: Session, process_id: str):
    return db.query(models.Process).filter(models.Process.id == process_id).first()

def create_process(db: Session, process: schemas.ProcessCreateSchema):
    process_data = process.dict()

    db_process = models.Process(
        id = str(uuid.uuid4()),
        **process_data
    )

    db.add(db_process)
    db.commit()
    db.refresh(db_process)
    return db_process

def delete_process(db: Session, process_id: str):
    db_process = get_process_by_id(db, process_id)
    if db_process:
        db.delete(db_process)
        db.commit()
    return db_process

def update_process(db: Session, process_id: str, process: schemas.ProcessCreateSchema):
    db_process = get_process_by_id(db, process_id)
    if db_process:
        update_data = process.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_process, key, value)
        db.commit()
        db.refresh(db_process)
    return db_process
