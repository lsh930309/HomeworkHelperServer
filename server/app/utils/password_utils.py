"""
비밀번호 해싱 및 검증 유틸리티
"""
from passlib.context import CryptContext

# bcrypt를 사용한 비밀번호 해싱 컨텍스트
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    평문 비밀번호를 bcrypt로 해싱

    Args:
        password: 평문 비밀번호

    Returns:
        str: 해싱된 비밀번호
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    평문 비밀번호와 해시 비밀번호 비교

    Args:
        plain_password: 평문 비밀번호
        hashed_password: 해싱된 비밀번호

    Returns:
        bool: 비밀번호가 일치하면 True, 아니면 False
    """
    return pwd_context.verify(plain_password, hashed_password)
