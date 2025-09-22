from sqlalchemy.orm import Session
import models
import schemas
import uuid

# process management funcions
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

# shortcut management functions
def get_shortcut_by_id(db: Session, shortcut_id: str):
    return db.query(models.WebShortcut).filter(models.WebShortcut.id == shortcut_id).first()

def get_shortcuts(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.WebShortcut).offset(skip).limit(limit).all()

def create_shortcut(db: Session, shortcut: schemas.WebShortcutCreate):
    db_shortcut = models.WebShortcut(
        id = str(uuid.uuid4()),
        **shortcut.dict()
    )
    db.add(db_shortcut)
    db.commit()
    db.refresh(db_shortcut)
    return db_shortcut

def update_shortcut(db: Session, shortcut_id: str, shortcut: schemas.WebShortcutCreate):
    db_shortcut = get_shortcut_by_id(db, shortcut_id)
    if db_shortcut:
        update_data = shortcut.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_shortcut, key, value)
        db.commit()
        db.refresh(db_shortcut)
    return db_shortcut

def delete_shortcut(db: Session, shortcut_id: str):
    db_shortcut = get_shortcut_by_id(db, shortcut_id)
    if db_shortcut:
        db.delete(db_shortcut)
        db.commit()
    return db_shortcut

# global setting management functions
def get_settings(db: Session):
    return db.query(models.GlobalSettings).first()

def update_settings(db: Session, settings: schemas.GlobalSettingsSchema):
    db_settings = get_settings(db)
    if db_settings:
        update_data = settings.dict()
        for key, value in update_data.items():
            setattr(db_settings, key, value)
        db.commit()
        db.refresh(db_settings)
    return db_settings
