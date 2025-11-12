"""
세션 API 라우터
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime
from app.core.database import get_db
from app.models.models import User, Session as SessionModel
from app.schemas.session import (
    SessionCreateRequest,
    SessionEndRequest,
    SessionResponse,
    SessionListResponse
)
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/sessions", tags=["세션"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    session_data: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    세션 시작 API

    - **process_id**: 프로세스 ID
    - **game_name**: 게임 이름
    """
    # 세션 생성
    new_session = SessionModel(
        user_id=current_user.id,
        process_id=session_data.process_id,
        game_name=session_data.game_name,
        start_ts=datetime.utcnow()
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    return new_session


@router.put("/{session_id}/end", response_model=SessionResponse)
def end_session(
    session_id: int,
    end_data: SessionEndRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    세션 종료 API

    - **session_id**: 종료할 세션 ID
    - **end_ts**: 종료 시각
    """
    # 세션 조회
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="세션을 찾을 수 없습니다."
        )

    # 권한 확인 (본인의 세션만 종료 가능)
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 세션을 종료할 권한이 없습니다."
        )

    # 이미 종료된 세션 확인
    if session.end_ts is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 종료된 세션입니다."
        )

    # 세션 종료 처리
    session.end_ts = end_data.end_ts
    session.duration = int((end_data.end_ts - session.start_ts).total_seconds())
    db.commit()
    db.refresh(session)

    return session


@router.get("", response_model=SessionListResponse)
def get_sessions(
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(10, ge=1, le=100, description="가져올 개수"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    세션 목록 조회 API (본인 세션만)

    - **skip**: 페이지네이션 - 건너뛸 개수 (기본값: 0)
    - **limit**: 페이지네이션 - 가져올 개수 (기본값: 10, 최대: 100)
    """
    # 전체 개수 조회
    total = db.query(SessionModel).filter(SessionModel.user_id == current_user.id).count()

    # 세션 목록 조회 (최신순)
    sessions = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == current_user.id)
        .order_by(SessionModel.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return SessionListResponse(
        sessions=sessions,
        total=total
    )


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    세션 상세 조회 API

    - **session_id**: 조회할 세션 ID
    """
    # 세션 조회
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="세션을 찾을 수 없습니다."
        )

    # 권한 확인 (본인의 세션만 조회 가능)
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 세션을 조회할 권한이 없습니다."
        )

    return session
