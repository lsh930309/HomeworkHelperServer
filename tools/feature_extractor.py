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

            import torch
            import torch.nn as nn
            import torchvision.models as models
            import torchvision.transforms as T

            # 디바이스 자동 감지
            if self.device is None:
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA를 사용할 수 없습니다. GPU가 필요합니다.")
                self.device = torch.device('cuda')

            # ResNet18 모델 로드 (fc layer를 Identity로 변경 → 512차원 출력)
            self.model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
            self.model.fc = nn.Identity()
            self.model.eval().to(self.device)

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

