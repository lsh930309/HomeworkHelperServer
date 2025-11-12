"""
예측 API 라우터
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.models.models import User, Session as SessionModel, Prediction
from app.schemas.prediction import (
    PredictionCreateRequest,
    PredictionResponse,
    PredictionListResponse
)
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/predictions", tags=["예측"])


@router.post("", response_model=PredictionResponse, status_code=status.HTTP_201_CREATED)
def create_prediction(
    prediction_data: PredictionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    AI 예측 생성 API

    - **session_id**: 세션 ID
    - **predicted_action**: 예측된 행동 (예: raid, daily_quest)
    - **predicted_value**: 예상 자원량
    - **confidence**: 신뢰도 (0.0 ~ 1.0)
    """
    # 세션 조회
    session = db.query(SessionModel).filter(SessionModel.id == prediction_data.session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="세션을 찾을 수 없습니다."
        )

    # 권한 확인 (본인의 세션에만 예측 생성 가능)
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 세션에 예측을 생성할 권한이 없습니다."
        )

    # 예측 생성
    new_prediction = Prediction(
        session_id=prediction_data.session_id,
        predicted_action=prediction_data.predicted_action,
        predicted_value=prediction_data.predicted_value,
        confidence=prediction_data.confidence
    )
    db.add(new_prediction)
    db.commit()
    db.refresh(new_prediction)

    return new_prediction


@router.get("", response_model=PredictionListResponse)
def get_predictions(
    session_id: Optional[int] = Query(None, description="세션 ID로 필터링"),
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(10, ge=1, le=100, description="가져올 개수"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    예측 목록 조회 API (본인 세션의 예측만)

    - **session_id**: (선택) 특정 세션의 예측만 조회
    - **skip**: 페이지네이션 - 건너뛸 개수 (기본값: 0)
    - **limit**: 페이지네이션 - 가져올 개수 (기본값: 10, 최대: 100)
    """
    # 기본 쿼리: 본인의 세션에 속한 예측만
    query = (
        db.query(Prediction)
        .join(SessionModel, Prediction.session_id == SessionModel.id)
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
                detail="이 세션의 예측을 조회할 권한이 없습니다."
            )
        query = query.filter(Prediction.session_id == session_id)

    # 전체 개수 조회
    total = query.count()

    # 예측 목록 조회 (최신순)
    predictions = (
        query
        .order_by(Prediction.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return PredictionListResponse(
        predictions=predictions,
        total=total
    )
