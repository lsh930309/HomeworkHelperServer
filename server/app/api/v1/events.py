"""
이벤트 API 라우터
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.models.models import User, Session as SessionModel, Event
from app.schemas.event import (
    EventCreateRequest,
    EventResponse,
    EventListResponse
)
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/events", tags=["이벤트"])


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    event_data: EventCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    이벤트 기록 API

    - **session_id**: 세션 ID
    - **event_type**: 이벤트 타입 (예: resource_change, action_start)
    - **resource_type**: 자원 타입 (예: stamina, currency)
    - **value**: 이벤트 값
    - **timestamp**: 이벤트 발생 시각
    """
    # 세션 조회
    session = db.query(SessionModel).filter(SessionModel.id == event_data.session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="세션을 찾을 수 없습니다."
        )

    # 권한 확인 (본인의 세션에만 이벤트 기록 가능)
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 세션에 이벤트를 기록할 권한이 없습니다."
        )

    # 이벤트 생성
    new_event = Event(
        session_id=event_data.session_id,
        event_type=event_data.event_type,
        resource_type=event_data.resource_type,
        value=event_data.value,
        timestamp=event_data.timestamp
    )
    db.add(new_event)
    db.commit()
    db.refresh(new_event)

    return new_event


@router.get("", response_model=EventListResponse)
def get_events(
    session_id: Optional[int] = Query(None, description="세션 ID로 필터링"),
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(10, ge=1, le=100, description="가져올 개수"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    이벤트 목록 조회 API (본인 세션의 이벤트만)

    - **session_id**: (선택) 특정 세션의 이벤트만 조회
    - **skip**: 페이지네이션 - 건너뛸 개수 (기본값: 0)
    - **limit**: 페이지네이션 - 가져올 개수 (기본값: 10, 최대: 100)
    """
    # 기본 쿼리: 본인의 세션에 속한 이벤트만
    query = (
        db.query(Event)
        .join(SessionModel, Event.session_id == SessionModel.id)
        .filter(SessionModel.user_id == current_user.id)
    )

    # session_id로 필터링 (옵션)
    if session_id is not None:
        # 세션 존재 여부 및 권한 확인
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="세션을 찾을 수 없습니다."
            )
        if session.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="이 세션의 이벤트를 조회할 권한이 없습니다."
            )
        query = query.filter(Event.session_id == session_id)

    # 전체 개수 조회
    total = query.count()

    # 이벤트 목록 조회 (시간순)
    events = (
        query
        .order_by(Event.timestamp.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return EventListResponse(
        events=events,
        total=total
    )
