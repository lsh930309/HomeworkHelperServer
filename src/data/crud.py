from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, IntegrityError
from src.data import models
from src.data import schemas
from typing import Optional
import uuid
import time
import logging

logger = logging.getLogger(__name__)

def db_retry_on_lock(func):
    """데이터베이스 락 발생 시 재시도하는 데코레이터"""
    def wrapper(*args, **kwargs):
        max_retries = 3
        retry_delay = 0.1  # 100ms

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    logger.warning(f"DB locked, retrying... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay * (attempt + 1))  # 지수 백오프
                else:
                    logger.error(f"DB operation failed after {attempt + 1} attempts: {e}")
                    raise
            except IntegrityError as e:
                logger.error(f"DB integrity error: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected DB error: {e}")
                raise

    return wrapper

# process management funcions
def get_processes(db: Session):
    return db.query(models.Process).all()

def get_process_by_id(db: Session, process_id: str):
    return db.query(models.Process).filter(models.Process.id == process_id).first()

@db_retry_on_lock
def create_process(db: Session, process: schemas.ProcessCreateSchema):
    process_data = process.dict()

    provided_id = process_data.pop('id', None)
    db_process = models.Process(
        id = provided_id if provided_id else str(uuid.uuid4()),
        **process_data
    )
    db.add(db_process)
    db.commit()
    db.refresh(db_process)
    return db_process

@db_retry_on_lock
def delete_process(db: Session, process_id: str):
    db_process = get_process_by_id(db, process_id)
    if db_process:
        db.delete(db_process)
        db.commit()
    return db_process

@db_retry_on_lock
def update_process(db: Session, process_id: str, process: schemas.ProcessCreateSchema):
    db_process = get_process_by_id(db, process_id)
    if db_process:
        # None 값을 전달하면 기존 값이 덮어써지는 문제 방지: None은 제외
        update_data = {k: v for k, v in process.dict(exclude_unset=True).items() if v is not None}
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

@db_retry_on_lock
def create_shortcut(db: Session, shortcut: schemas.WebShortcutCreate):
    shortcut_data = shortcut.dict()
    provided_id = shortcut_data.pop('id', None)
    db_shortcut = models.WebShortcut(
        id = provided_id if provided_id else str(uuid.uuid4()),
        **shortcut_data
    )
    db.add(db_shortcut)
    db.commit()
    db.refresh(db_shortcut)
    return db_shortcut

@db_retry_on_lock
def update_shortcut(db: Session, shortcut_id: str, shortcut: schemas.WebShortcutCreate):
    db_shortcut = get_shortcut_by_id(db, shortcut_id)
    if db_shortcut:
        update_data = shortcut.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_shortcut, key, value)
        db.commit()
        db.refresh(db_shortcut)
    return db_shortcut

@db_retry_on_lock
def delete_shortcut(db: Session, shortcut_id: str):
    db_shortcut = get_shortcut_by_id(db, shortcut_id)
    if db_shortcut:
        db.delete(db_shortcut)
        db.commit()
    return db_shortcut

# global setting management functions
@db_retry_on_lock
def get_settings(db: Session):
    """ GlobalSettings를 조회합니다. 없으면 기본값으로 생성하여 반환합니다. """
    db_settings = db.query(models.GlobalSettings).filter(models.GlobalSettings.id == 1).first()

    if not db_settings:
        print("기본 설정을 생성합니다.")
        # 기본 스키마로부터 딕셔너리를 만듭니다.
        default_data = schemas.GlobalSettingsSchema().dict()
        # id를 추가하고 DB 모델 객체를 생성합니다.
        db_settings = models.GlobalSettings(id=1, **default_data)

        db.add(db_settings)
        db.commit()
        db.refresh(db_settings)

    return db_settings

@db_retry_on_lock
def update_settings(db: Session, settings: schemas.GlobalSettingsSchema):
    db_settings = get_settings(db)
    if db_settings:
        update_data = settings.dict()
        for key, value in update_data.items():
            setattr(db_settings, key, value)
        db.commit()
        db.refresh(db_settings)
    return db_settings


# process session management functions
@db_retry_on_lock
def create_session(db: Session, session: schemas.ProcessSessionCreate):
    """새로운 프로세스 세션 시작 기록"""
    db_session = models.ProcessSession(**session.dict())
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    return db_session


@db_retry_on_lock
def end_session(db: Session, session_id: int, end_timestamp: float, stamina_at_end: Optional[int] = None):
    """프로세스 세션 종료 기록"""
    db_session = db.query(models.ProcessSession).filter(models.ProcessSession.id == session_id).first()
    if db_session:
        db_session.end_timestamp = end_timestamp
        db_session.session_duration = end_timestamp - db_session.start_timestamp
        if stamina_at_end is not None:
            db_session.stamina_at_end = stamina_at_end
        db.commit()
        db.refresh(db_session)
    return db_session


def get_active_session_by_process_id(db: Session, process_id: str):
    """특정 프로세스의 활성 세션 조회 (end_timestamp가 NULL인 세션)"""
    return db.query(models.ProcessSession).filter(
        models.ProcessSession.process_id == process_id,
        models.ProcessSession.end_timestamp == None
    ).first()


def get_sessions_by_process_id(db: Session, process_id: str, skip: int = 0, limit: int = 100):
    """특정 프로세스의 모든 세션 조회"""
    return db.query(models.ProcessSession).filter(
        models.ProcessSession.process_id == process_id
    ).order_by(models.ProcessSession.start_timestamp.desc()).offset(skip).limit(limit).all()


def get_all_sessions(db: Session, skip: int = 0, limit: int = 100):
    """모든 세션 조회"""
    return db.query(models.ProcessSession).order_by(
        models.ProcessSession.start_timestamp.desc()
    ).offset(skip).limit(limit).all()
