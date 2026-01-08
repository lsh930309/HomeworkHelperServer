#!/usr/bin/env python3
"""
ResNet 기반 Feature Extractor
비디오 프레임에서 의미적 특징을 추출하여 유사도 계산
"""

import sys
from pathlib import Path
from typing import List, Optional
import numpy as np
import cv2


class FeatureExtractor:
    """
    ResNet18 기반 Feature Extractor

    비디오 프레임 → 512차원 Feature Vector 추출
    - L2 정규화 자동 적용
    - GPU/CPU 자동 감지
    - 배치 처리 지원
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
        """
        ResNet18 모델 초기화

        clustering.py의 build_resnet18() 로직과 동일
        """
        try:
            # PyTorch 설치 경로 추가 (패키징 환경 호환)
            self._add_pytorch_path()

            import torch
            import torch.nn as nn
            import torchvision.models as models
            import torchvision.transforms as T

            # 디바이스 자동 감지
            if self.device is None:
                self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

            # ResNet18 모델 로드 (fc layer를 Identity로 변경 → 512차원 출력)
            self.model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
            self.model.fc = nn.Identity()  # 512차원 feature vector 출력
            self.model.eval().to(self.device)

            # 이미지 전처리 변환 (ImageNet 표준)
            self.transform = T.Compose([
                T.ToPILImage(),
                T.Resize(224, interpolation=T.InterpolationMode.BILINEAR),
                T.CenterCrop(224),
                T.ToTensor(),
                T.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
            ])

            print(f"✅ ResNet18 Feature Extractor 초기화 완료 (디바이스: {self.device})")

        except ImportError as e:
            print(f"❌ PyTorch를 import할 수 없습니다: {e}")
            print("   GPU 가속을 사용하려면 PyTorch를 설치해주세요.")
            raise
        except Exception as e:
            print(f"❌ Feature Extractor 초기화 실패: {e}")
            raise

    def _add_pytorch_path(self):
        """
        PyTorch 설치 경로를 sys.path에 추가 (패키징 환경 호환)
        """
        try:
            # src/utils 경로 추가 (PyTorchInstaller import용)
            if getattr(sys, 'frozen', False):
                # PyInstaller 패키징 환경
                utils_dir = Path(sys.executable).parent / "_internal" / "src"
            else:
                # 개발 환경
                script_dir = Path(__file__).parent.parent
                utils_dir = script_dir / "src"

            if utils_dir.exists() and str(utils_dir) not in sys.path:
                sys.path.insert(0, str(utils_dir))

            # PyTorchInstaller로 경로 추가
            try:
                from utils.pytorch_installer import PyTorchInstaller
                installer = PyTorchInstaller.get_instance()

                if installer.is_pytorch_installed():
                    installer.add_to_path()
            except ImportError:
                # PyTorchInstaller를 찾을 수 없는 경우 (시스템 PyTorch 사용)
                pass

        except Exception:
            # 경로 추가 실패는 무시 (시스템 PyTorch 사용)
            pass

    def extract_frame_features(self, frames: List[np.ndarray]) -> np.ndarray:
        """
        프레임 배치에서 feature 추출

        Args:
            frames: BGR 이미지 리스트 (OpenCV 포맷)

        Returns:
            L2 정규화된 feature 배열 (N, 512)
        """
        try:
            import torch

            if not frames:
                return np.array([])

            # 이미지 전처리 (배치)
            tensor_list = []
            for frame in frames:
                # BGR → RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # Transform 적용
                tensor = self.transform(frame_rgb)
                tensor_list.append(tensor)

            # 배치 텐서 생성
            batch_tensor = torch.stack(tensor_list).to(self.device, non_blocking=True)

            # Feature 추출
            with torch.inference_mode():
                if self.use_fp16 and self.device.type == 'cuda':
                    with torch.autocast(device_type='cuda', dtype=torch.float16):
                        features = self.model(batch_tensor)
                else:
                    features = self.model(batch_tensor)

                # L2 정규화 (코사인 유사도 계산용)
                features = torch.nn.functional.normalize(features, dim=1)

                # CPU로 이동 및 numpy 변환
                features_np = features.cpu().numpy()

            return features_np

        except Exception as e:
            print(f"⚠️ Feature 추출 실패: {e}")
            # Fallback: 빈 배열 반환
            return np.array([])

    def calculate_cosine_similarity(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        """
        두 feature 간 코사인 유사도 계산

        Args:
            feat1: Feature vector 1 (512차원, L2 정규화됨)
            feat2: Feature vector 2 (512차원, L2 정규화됨)

        Returns:
            코사인 유사도 (0~1, 높을수록 유사)
        """
        # L2 정규화가 이미 적용되어 있으므로 내적만 계산
        similarity = np.dot(feat1, feat2)

        # 수치 오류로 인한 범위 초과 방지
        similarity = np.clip(similarity, 0.0, 1.0)

        return float(similarity)

    def calculate_similarity_batch(
        self,
        frame_pairs: List[tuple]
    ) -> List[float]:
        """
        배치 단위 유사도 계산 (GPU 최적화)

        Args:
            frame_pairs: [(frame1, frame2), ...] 프레임 쌍 리스트

        Returns:
            유사도 점수 리스트
        """
        if not frame_pairs:
            return []

        try:
            # 모든 프레임을 리스트로 분리
            frames1 = [pair[0] for pair in frame_pairs]
            frames2 = [pair[1] for pair in frame_pairs]

            # 배치로 feature 추출
            features1 = self.extract_frame_features(frames1)
            features2 = self.extract_frame_features(frames2)

            # 페어별 코사인 유사도 계산
            similarities = []
            for feat1, feat2 in zip(features1, features2):
                sim = self.calculate_cosine_similarity(feat1, feat2)
                similarities.append(sim)

            return similarities

        except Exception as e:
            print(f"⚠️ 배치 유사도 계산 실패: {e}")
            # Fallback: 단일 계산
            similarities = []
            for frame1, frame2 in frame_pairs:
                feat1 = self.extract_frame_features([frame1])
                feat2 = self.extract_frame_features([frame2])
                if len(feat1) > 0 and len(feat2) > 0:
                    sim = self.calculate_cosine_similarity(feat1[0], feat2[0])
                    similarities.append(sim)
                else:
                    similarities.append(0.0)
            return similarities

    def cleanup(self):
        """
        리소스 정리 (GPU 메모리 해제)
        """
        try:
            import torch
            if self.device and self.device.type == 'cuda':
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except:
            pass
