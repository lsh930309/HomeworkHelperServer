from pathlib import Path
import csv
import shutil
import numpy as np
from collections import defaultdict
from PIL import Image
from tqdm import tqdm
from natsort import natsorted
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import torchvision.transforms as T
import torchvision.models as models
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

# --- 기존 유틸 그대로 사용 (필요한 부분만 발췌) ---

TARGET_SIZE = (1656, 2338)


class ImageFolderDataset(Dataset):
    def __init__(self, root: str, image_size: int = 224):
        self.paths = [
            p for p in Path(root).glob("**/*.png")
            if "clustered" not in p.as_posix() and "@eaDir" not in p.parts
        ]
        if not self.paths:
            raise FileNotFoundError(f"No images found under: {root}")
        self.tf = T.Compose([
            T.Resize(image_size, interpolation=T.InterpolationMode.BILINEAR),
            T.CenterCrop(image_size),
            T.ToTensor(),
            T.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229,0.224,0.225)),
        ])

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, idx):
        p = self.paths[idx]
        img = Image.open(p).convert("RGB")
        return self.tf(img), str(p)


def build_resnet18(device: torch.device):
    model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
    model.fc = nn.Identity()  # -> (B, 512)
    model.eval().to(device)
    return model


@torch.inference_mode()
def extract_features(loader, model, device, use_fp16: bool = True):
    feats, all_paths = [], []
    autocast_dtype = torch.float16 if (use_fp16 and device.type == "cuda") else None
    for imgs, paths in tqdm(loader, desc="Extracting features"):
        imgs = imgs.to(device, non_blocking=True)
        if autocast_dtype is not None:
            with torch.autocast(device_type="cuda", dtype=autocast_dtype):
                f = model(imgs)
        else:
            f = model(imgs)
        f = torch.nn.functional.normalize(f, dim=1)
        feats.append(f.cpu().numpy())
        all_paths.extend(paths)
    feats = np.concatenate(feats, axis=0)
    return feats, all_paths


def run_kmeans(X: np.ndarray, k: int, seed: int = 42):
    km = KMeans(n_clusters=k, n_init="auto", random_state=seed)
    labels = km.fit_predict(X)
    return labels, km


def maybe_pca(X: np.ndarray, pca_dim: int | None, seed: int = 42):
    if pca_dim is None or pca_dim <= 0 or pca_dim >= X.shape[1]:
        return X, None
    pca = PCA(n_components=pca_dim, random_state=seed, svd_solver="auto", whiten=False)
    Xr = pca.fit_transform(X)
    return Xr, pca


def save_assignments(paths, labels, out_csv: Path):
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path", "cluster"])
        for p, c in zip(paths, labels):
            w.writerow([p, int(c)])


def print_cluster_summary(paths, labels):
    from collections import Counter, defaultdict
    cnt = Counter(labels.tolist())
    print("\n[Cluster sizes]")
    for cid, n in sorted(cnt.items()):
        print(f"  cluster {cid}: {n}")

    bucket = defaultdict(list)
    for p, c in zip(paths, labels):
        bucket[c].append(p)

    print("\n[Examples per cluster]")
    for cid in sorted(bucket.keys()):
        print(f"  cluster {cid}:")
        for ex in bucket[cid]:
            print(f"    - {ex}")


def copy(paths, labels, save_dir):
    bucket = defaultdict(list)
    for p, c in zip(paths, labels):
        bucket[c].append(p)

    if Path(save_dir).exists():
        shutil.rmtree(
            save_dir,
        )

    for cid in sorted(bucket.keys()):
        for ex in bucket[cid]:
            folder_name = "-".join(natsorted([Path(i).stem for i in bucket[cid]]))
            save_path = Path(save_dir) / f'{folder_name}/{Path(ex).name}'
            save_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            _ = shutil.copy2(
                ex,
                save_path,
            )


def main(
    num_clusters: int,
    pca_dim: int = 256,   # <=512, 0 또는 음수면 비활성
    images_dir: str = "/mnt/AI_NAS/Data/현대캐피탈/forms/merged-3/kie/internal",
    save_dir: str = "/mnt/AI_NAS/Data/현대캐피탈/forms/merged-3/kie/internal/clustered",
    batch_size: int = 8,
    num_workers: int = 8,
    seed: int = 42,
    cpu: bool = False,
    no_fp16: bool = False,
):
    """
    ResNet18 features -> (PCA) -> KMeans clustering

    Args:
      image_dir: 이미지가 들어있는 디렉토리 (필수)
      out_dir: 결과 저장 디렉토리
      k: KMeans 클러스터 수
      batch_size: 배치 크기
      num_workers: DataLoader workers
      image_size: 입력 리사이즈 크기
      pca_dim: PCA 차원(0/neg -> 비활성)
      seed: random seed
      cpu: True면 CPU 강제
      no_fp16: True면 CUDA FP16 autocast 비활성
    """
    device = torch.device("cpu" if cpu or not torch.cuda.is_available() else "cuda")
    print(f"[Device] {device}")

    ds = ImageFolderDataset(
        images_dir,
        image_size=TARGET_SIZE[1],
    )
    dl = DataLoader(
        ds,
        batch_size=batch_size,
        num_workers=num_workers,
        shuffle=False,
        pin_memory=(device.type=="cuda"),
        drop_last=False,
        persistent_workers=(num_workers > 0)
    )
    print(f"[Data] {len(ds)} images found")

    model = build_resnet18(device)

    feats, paths = extract_features(
        loader=dl, model=model, device=device, use_fp16=not no_fp16
    )

    feats2, pca = maybe_pca(feats, pca_dim, seed=seed)
    if pca is not None:
        print(f"[PCA] Reduced {feats.shape[1]} -> {feats2.shape[1]} dims")

    labels, km = run_kmeans(feats2, k=num_clusters, seed=seed)

    sscore = None
    try:
        if len(np.unique(labels)) > 1:
            sample_cap = 20000
            idx = np.random.RandomState(seed).permutation(len(labels))[:sample_cap]
            sscore = silhouette_score(feats2[idx], labels[idx], metric="euclidean")
            print(f"[Silhouette] {sscore:.4f}")
    except Exception as e:
        print(f"[Silhouette] skipped: {e}")

    copy(paths, labels, save_dir)
    if sscore is not None:
        print(f"Silhouette score: {sscore:.4f}")

if __name__ == "__main__":
    import fire
    fire.Fire(main)
