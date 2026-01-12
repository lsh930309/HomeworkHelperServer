#!/usr/bin/env python3
"""
ResNet 기반 Feature Extractor (GPU 최적화 버전)
비디오 프레임에서 의미적 특징을 추출하여 유사도 계산
- 모든 연산을 GPU에서 수행
- CPU-GPU 데이터 전송 최소화
- 배치 유사도 계산 GPU 최적화
"""

import sys
from pathlib import Path
from typing import List
import numpy as np
import cv2


class FeatureExtractor:
    """
    ResNet18 기반 Feature Extractor (GPU 최적화)

    비디오 프레임 → 512차원 Feature Vector 추출
    - 모든 연산 GPU에서 수행
    - L2 정규화 자동 적용
    - 배치 유사도 계산 GPU 최적화
    """

    def __init__(self, device=None, use_fp16: bool = True):
        """
        Feature Extractor 초기화

        Args:
            device: torch.device (None이면 자동 감지)
            use_fp16: FP16 사용 여부 (GPU에서만)
        """
        self.device = device
        self.use_fp16 = use_fp16
        self.model = None
        self.transform = None

        # PyTorch import 및 모델 로드
        self._init_model()

    def _init_model(self):
        """ResNet18 모델 초기화"""
        try:
            self._add_pytorch_path()

            # PyAV import 문제 우회 (torchvision이 PyAV를 체크하기 전에 처리)
            # PyAV가 패키징 환경에서 제대로 로드되지 않을 때를 대비
            import types

            def _create_fake_av_logging():
                """가짜 av.logging 모듈 생성 (필요한 함수 포함)"""
                fake_logging = types.ModuleType('av.logging')
                # torchvision이 사용하는 함수들을 빈 함수로 추가
                fake_logging.set_level = lambda level: None
                fake_logging.get_level = lambda: 0
                return fake_logging

            try:
                import av
                # av.logging이 없거나 set_level이 없으면 추가
                if not hasattr(av, 'logging'):
                    av.logging = _create_fake_av_logging()
                    sys.modules['av.logging'] = av.logging
                elif not hasattr(av.logging, 'set_level'):
                    # logging 모듈은 있지만 set_level이 없는 경우
                    av.logging.set_level = lambda level: None
                    av.logging.get_level = lambda: 0
            except ImportError:
                # av가 없으면 가짜 모듈 생성
                fake_av = types.ModuleType('av')
                fake_av.logging = _create_fake_av_logging()
                sys.modules['av'] = fake_av
                sys.modules['av.logging'] = fake_av.logging

            # PyTorch import 시도 (상세한 에러 메시지)
            try:
                import torch
            except ImportError as e:
                # 더 상세한 에러 정보 수집
                error_details = f"\n   - 에러 메시지: {str(e)}"
                error_details += f"\n   - sys.path 개수: {len(sys.path)}"

                # PyTorch 경로 확인
                pytorch_paths = [p for p in sys.path if 'pytorch' in p.lower()]
                if pytorch_paths:
                    error_details += f"\n   - PyTorch 경로: {pytorch_paths[0]}"
                else:
                    error_details += "\n   - PyTorch 경로를 sys.path에서 찾을 수 없음"

                raise RuntimeError(f"PyTorch를 import할 수 없습니다:{error_details}")

            import torch.nn as nn

            # torchvision import 시 PyAV 관련 경고 무시
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                import torchvision.models as models
                import torchvision.transforms as T

            # 디바이스 자동 감지
            if self.device is None:
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA를 사용할 수 없습니다. GPU가 필요합니다.")
                self.device = torch.device('cuda')

            # ResNet18 모델 로드 (fc layer를 Identity로 변경 → 512차원 출력)
            print("🔄 ResNet18 모델 로딩 중...")
            try:
                self.model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
                print("✅ ResNet18 weights 로드 완료")
            except Exception as e:
                print(f"⚠️ ResNet18 weights 로드 실패: {e}")
                print("   기본 모델로 대체 시도...")
                # weights 다운로드 실패 시 pretrained=False로 시도
                self.model = models.resnet18(weights=None)
                print("⚠️ 사전 학습되지 않은 모델 사용 (정확도 낮음)")

            self.model.fc = nn.Identity()
            self.model.eval()

            print(f"🔄 모델을 GPU로 이동 중... (device: {self.device})")
            self.model = self.model.to(self.device)
            print("✅ 모델 GPU 이동 완료")

            # FP16 사용 시 모델도 FP16으로
            if self.use_fp16 and self.device.type == 'cuda':
                self.model = self.model.half()

            # ImageNet 정규화 파라미터 (GPU 텐서로 미리 생성)
            self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device).view(1, 3, 1, 1)
            self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device).view(1, 3, 1, 1)
            if self.use_fp16:
                self.mean = self.mean.half()
                self.std = self.std.half()

            print(f"✅ ResNet18 Feature Extractor 초기화 완료 (GPU: {torch.cuda.get_device_name(0)})")

        except ImportError as e:
            raise RuntimeError(f"PyTorch를 import할 수 없습니다: {e}")
        except Exception as e:
            raise RuntimeError(f"Feature Extractor 초기화 실패: {e}")

    def _add_pytorch_path(self):
        """PyTorch 설치 경로를 sys.path에 추가"""
        try:
            # PyTorch import에 필요한 표준 라이브러리 모듈들을 미리 import
            # (PyInstaller 패키징 환경에서 발생할 수 있는 import 에러 방지)
            try:
                import modulefinder
                import importlib
                import importlib.util
                import importlib.machinery
                import pkgutil
                import inspect
            except ImportError as e:
                print(f"⚠️ 표준 라이브러리 import 실패: {e}")

            if getattr(sys, 'frozen', False):
                utils_dir = Path(sys.executable).parent / "_internal" / "src"
            else:
                script_dir = Path(__file__).parent.parent
                utils_dir = script_dir / "src"

            if utils_dir.exists() and str(utils_dir) not in sys.path:
                sys.path.insert(0, str(utils_dir))

            try:
                from utils.pytorch_installer import PyTorchInstaller
                installer = PyTorchInstaller.get_instance()
                if installer.is_pytorch_installed():
                    installer.add_to_path()
            except ImportError:
                pass
        except Exception:
            pass

    def _preprocess_frames_gpu(self, frames: List[np.ndarray]):
        """
        프레임을 GPU에서 직접 전처리 (CPU 연산 최소화)

        Args:
            frames: BGR 이미지 리스트 (OpenCV 포맷)

        Returns:
            전처리된 GPU 텐서 (N, 3, 224, 224)
        """
        import torch
        import torch.nn.functional as F

        # BGR → RGB 변환 및 텐서 변환 (배치로 한번에)
        batch_np = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in frames])
        
        # NumPy → Torch (GPU로 직접 이동, non_blocking)
        batch_tensor = torch.from_numpy(batch_np).to(self.device, non_blocking=True)
        
        # (N, H, W, C) → (N, C, H, W)
        batch_tensor = batch_tensor.permute(0, 3, 1, 2)
        
        # FP16/FP32 변환 및 정규화 [0, 255] → [0, 1]
        if self.use_fp16:
            batch_tensor = batch_tensor.half() / 255.0
        else:
            batch_tensor = batch_tensor.float() / 255.0
        
        # 리사이즈 (224x224)
        batch_tensor = F.interpolate(batch_tensor, size=(224, 224), mode='bilinear', align_corners=False)
        
        # ImageNet 정규화 (GPU에서 직접)
        batch_tensor = (batch_tensor - self.mean) / self.std
        
        return batch_tensor

    def extract_frame_features(self, frames: List[np.ndarray]) -> np.ndarray:
        """
        프레임 배치에서 feature 추출

        Args:
            frames: BGR 이미지 리스트 (OpenCV 포맷)

        Returns:
            L2 정규화된 feature 배열 (N, 512)
        """
        import torch

        if not frames:
            return np.array([])

        try:
            # GPU에서 전처리
            batch_tensor = self._preprocess_frames_gpu(frames)

            # Feature 추출
            with torch.inference_mode():
                features = self.model(batch_tensor)

                # L2 정규화 (코사인 유사도 계산용)
                features = torch.nn.functional.normalize(features, dim=1)

                # CPU로 이동 및 numpy 변환
                features_np = features.float().cpu().numpy()

            return features_np

        except Exception as e:
            print(f"❌ Feature 추출 중 오류: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _extract_features_gpu(self, frames: List[np.ndarray]):
        """
        프레임 배치에서 feature 추출 (GPU 텐서 유지)

        Args:
            frames: BGR 이미지 리스트

        Returns:
            L2 정규화된 GPU 텐서 (N, 512)
        """
        import torch

        if not frames:
            return None

        # GPU에서 전처리
        batch_tensor = self._preprocess_frames_gpu(frames)

        # Feature 추출 (GPU 유지)
        with torch.inference_mode():
            features = self.model(batch_tensor)
            # L2 정규화
            features = torch.nn.functional.normalize(features, dim=1)

        return features

    def calculate_cosine_similarity(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        """
        두 feature 간 코사인 유사도 계산

        Args:
            feat1: Feature vector 1 (512차원, L2 정규화됨)
            feat2: Feature vector 2 (512차원, L2 정규화됨)

        Returns:
            코사인 유사도 (0~1, 높을수록 유사)
        """
        similarity = np.dot(feat1, feat2)
        return float(np.clip(similarity, 0.0, 1.0))

    def calculate_similarity_batch(self, frame_pairs: List[tuple]) -> List[float]:
        """
        배치 단위 유사도 계산 (GPU 최적화)

        모든 프레임을 한 번에 GPU로 전송하고,
        유사도 계산도 GPU에서 직접 수행하여 데이터 전송 최소화

        Args:
            frame_pairs: [(frame1, frame2), ...] 프레임 쌍 리스트

        Returns:
            유사도 점수 리스트
        """
        import torch

        if not frame_pairs:
            return []

        n = len(frame_pairs)
        
        # 모든 프레임을 하나의 리스트로 펼치기 (2N개)
        all_frames = []
        for f1, f2 in frame_pairs:
            all_frames.append(f1)
            all_frames.append(f2)

        # 한 번에 feature 추출 (GPU 유지)
        all_features = self._extract_features_gpu(all_frames)

        if all_features is None:
            return [0.0] * n

        # 짝수/홀수 인덱스로 분리
        features1 = all_features[0::2]  # 0, 2, 4, ...
        features2 = all_features[1::2]  # 1, 3, 5, ...

        # GPU에서 직접 배치 코사인 유사도 계산 (내적)
        # 이미 L2 정규화되어 있으므로 내적 = 코사인 유사도
        with torch.inference_mode():
            similarities = (features1 * features2).sum(dim=1)
            similarities = torch.clamp(similarities, 0.0, 1.0)
            similarities_list = similarities.float().cpu().tolist()

        return similarities_list

    def cleanup(self):
        """리소스 정리 (GPU 메모리 해제)"""
        try:
            import torch
            if self.device and self.device.type == 'cuda':
                del self.model
                del self.mean
                del self.std
                self.model = None
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except:
            pass

