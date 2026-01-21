from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session

from src.data import models
from src.data import crud
from src.data import schemas
from src.data.database import SessionLocal, engine, auto_migrate_database

# 앱 시작 시 자동 마이그레이션 실행 (기존 DB에 새 컬럼 추가)
auto_migrate_database()

# 테이블 생성 (새 DB인 경우)
models.Base.metadata.create_all(bind=engine)


app = FastAPI()

# load database...
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# create / read / update / delete [managed processes]
@app.get("/processes", response_model=List[schemas.ProcessSchema])
def get_all_processes(db: Session = Depends(get_db)):
    processes = crud.get_processes(db)
    return processes

@app.get("/processes/{process_id}", response_model=schemas.ProcessSchema)
def get_process_by_id(process_id: str, db: Session = Depends(get_db)):
    db_process = crud.get_process_by_id(db=db, process_id=process_id)
    if db_process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    return db_process

@app.post("/processes", response_model=schemas.ProcessSchema, status_code=201)
def create_new_process(process_data: schemas.ProcessCreateSchema, db: Session = Depends(get_db)):
    return crud.create_process(db = db, process = process_data)

@app.put("/processes/{process_id}", response_model=schemas.ProcessSchema)
def update_existing_process(process_id: str, process_data: schemas.ProcessCreateSchema, db: Session = Depends(get_db)):
    updated_process = crud.update_process(db = db, process_id = process_id, process = process_data)
    if updated_process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    return updated_process

@app.delete("/processes/{process_id}")
def delete_existing_process(process_id: str, db: Session = Depends(get_db)):
    deleted_process = crud.delete_process(db = db, process_id = process_id)
    if deleted_process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    return {"message": "프로세스가 삭제되었습니다."}

# create / read / update / delete [web shortcuts]
@app.get("/shortcuts", response_model=List[schemas.WebShortcutSchema])
def get_all_shortcuts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    shortcuts = crud.get_shortcuts(db, skip=skip, limit=limit)
    return shortcuts

@app.get("/shortcuts/{shortcut_id}", response_model=schemas.WebShortcutSchema)
def get_shortcut_by_id(shortcut_id: str, db: Session = Depends(get_db)):
    db_shortcut = crud.get_shortcut_by_id(db, shortcut_id)
    if db_shortcut is None:
        raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
    return db_shortcut

@app.post("/shortcuts", response_model=schemas.WebShortcutSchema, status_code=201)
def create_new_shortcut(shortcut_data: schemas.WebShortcutCreate, db: Session = Depends(get_db)):
    return crud.create_shortcut(db = db, shortcut = shortcut_data)

@app.put("/shortcuts/{shortcut_id}", response_model=schemas.WebShortcutSchema)
def update_existing_shortcut(shortcut_id: str, shortcut_data: schemas.WebShortcutCreate, db: Session = Depends(get_db)):
    updated_shortcut = crud.update_shortcut(db = db, shortcut_id = shortcut_id, shortcut = shortcut_data)
    if updated_shortcut is None:
        raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
    return updated_shortcut

@app.delete("/shortcuts/{shortcut_id}")
def delete_existing_shortcut(shortcut_id: str, db: Session = Depends(get_db)):
    deleted_shortcut = crud.delete_shortcut(db = db, shortcut_id = shortcut_id)
    if deleted_shortcut is None:
        raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
    return {"message": "웹 바로 가기가 삭제되었습니다."}

# read / update [global settings]
@app.get("/settings", response_model=schemas.GlobalSettingsSchema)
def get_global_settings(db: Session = Depends(get_db)):
    return crud.get_settings(db)

@app.put("/settings", response_model=schemas.GlobalSettingsSchema)
def update_global_settings(settings_data: schemas.GlobalSettingsSchema, db: Session = Depends(get_db)):
    return crud.update_settings(db = db, settings = settings_data)


# create / read / update [process sessions]
@app.post("/sessions", response_model=schemas.ProcessSessionSchema, status_code=201)
def create_new_session(session_data: schemas.ProcessSessionCreate, db: Session = Depends(get_db)):
    """새로운 프로세스 세션 시작"""
    return crud.create_session(db=db, session=session_data)


@app.put("/sessions/{session_id}/end", response_model=schemas.ProcessSessionSchema)
def end_process_session(session_id: int, end_data: schemas.ProcessSessionUpdate, db: Session = Depends(get_db)):
    """프로세스 세션 종료"""
    ended_session = crud.end_session(db=db, session_id=session_id, end_timestamp=end_data.end_timestamp)
    if ended_session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return ended_session


@app.get("/sessions/process/{process_id}", response_model=List[schemas.ProcessSessionSchema])
def get_sessions_by_process(process_id: str, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """특정 프로세스의 세션 이력 조회"""
    return crud.get_sessions_by_process_id(db=db, process_id=process_id, skip=skip, limit=limit)


@app.get("/sessions/process/{process_id}/active", response_model=schemas.ProcessSessionSchema)
def get_active_session(process_id: str, db: Session = Depends(get_db)):
    """특정 프로세스의 현재 활성 세션 조회"""
    session = crud.get_active_session_by_process_id(db=db, process_id=process_id)
    if session is None:
        raise HTTPException(status_code=404, detail="활성 세션이 없습니다.")
    return session


@app.get("/sessions", response_model=List[schemas.ProcessSessionSchema])
def get_all_sessions_list(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """모든 세션 조회"""
    return crud.get_all_sessions(db=db, skip=skip, limit=limit)
