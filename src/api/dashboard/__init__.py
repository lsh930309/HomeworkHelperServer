# Dashboard 모듈
"""대시보드 API 모듈 - FastAPI 라우터와 정적 파일 서빙"""

from .routes import router
from .settings import load_settings, save_settings

__all__ = ['router', 'load_settings', 'save_settings']
