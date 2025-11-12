"""
FastAPI 애플리케이션 엔트리포인트
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db

# FastAPI 앱 생성
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS 미들웨어 설정 (Android 앱 연동)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행"""
    print(f"🚀 {settings.PROJECT_NAME} v{settings.VERSION} 시작")
    print(f"📡 API 문서: http://{settings.API_HOST}:{settings.API_PORT}/docs")

    # 데이터베이스 초기화 (테이블 생성)
    # 프로덕션에서는 Alembic 마이그레이션 사용
    init_db()


@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 실행"""
    print("🛑 서버 종료")


# 기본 라우트
@app.get("/")
def read_root():
    """루트 엔드포인트"""
    return {
        "message": f"{settings.PROJECT_NAME}",
        "version": settings.VERSION,
        "docs": "/docs",
        "status": "running"
    }


@app.get("/health")
def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "ok",
        "version": settings.VERSION
    }


# API 라우터 등록
from app.api.v1 import auth, sessions, events

app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(sessions.router, prefix=settings.API_PREFIX)
app.include_router(events.router, prefix=settings.API_PREFIX)
