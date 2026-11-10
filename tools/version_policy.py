"""Version allocation on the Mac and the immutable input consumed by native builders."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

START_VERSIONS = {"host": "1.6.0", "client": "1.0.0"}
TAG_PREFIX = {"host": "H", "client": "C"}
START_TAGS = {product: f"{TAG_PREFIX[product]}/v{version}" for product, version in START_VERSIONS.items()}
SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
DEV_VERSION = re.compile(r"dev\.([1-9][0-9]*)")
COMMIT = re.compile(r"[0-9a-f]{40}")
MERGE_MARKER = re.compile(r"HomeworkHelper-Release: PR #[1-9][0-9]* (host|client|none) (minor|major)")
HOST_FILES = {"homework_helper.pyw", "homework_helper_service.py", "homework_helper.spec", "installer.iss", "requirements.txt"}
CLIENT_FILES = {
    "clients/macos/Package.swift",
    "clients/macos/Package.resolved",
    "tools/package_macos_remote_app.py",
    "tools/ensure_macos_local_codesign_identity.py",
}
SHARED_FILES = {"build.py", "assets/icons/app/app_icon.png"}


class VersionPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildVersion:
    product: str
    version: str
    commit: str
    base_version: str

    def __post_init__(self) -> None:
        if self.product not in START_VERSIONS or not COMMIT.fullmatch(self.commit):
            raise VersionPolicyError("빌드 제품 또는 소스 커밋이 올바르지 않습니다.")
        if not SEMVER.fullmatch(self.base_version):
            raise VersionPolicyError("빌드의 숫자 기준 버전이 올바르지 않습니다.")
        if not DEV_VERSION.fullmatch(self.version) and self.version != self.base_version:
            raise VersionPolicyError("빌드 버전은 숫자 정식 버전 또는 dev.N이어야 합니다.")

    @property
    def tag(self) -> str:
        if not SEMVER.fullmatch(self.version):
            raise VersionPolicyError("개발 버전에는 정식 태그를 붙일 수 없습니다.")
        return f"{TAG_PREFIX[self.product]}/v{self.version}"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> BuildVersion:
        try:
            return cls(**json.loads(text))
        except (TypeError, ValueError) as exc:
            raise VersionPolicyError("빌드 버전 스냅숏 형식이 올바르지 않습니다.") from exc


def read_snapshot(path: Path, *, product: str, commit: str) -> BuildVersion:
    try:
        snapshot = BuildVersion.from_json(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise VersionPolicyError(f"{path.name} 빌드 버전 스냅숏을 읽을 수 없습니다.") from exc
    if snapshot.product != product or snapshot.commit != commit:
        raise VersionPolicyError("빌드 버전 스냅숏과 현재 제품 또는 소스 커밋이 다릅니다.")
    return snapshot


def classify_paths(paths: Iterable[str]) -> set[str]:
    products = set()
    for path in paths:
        if path in SHARED_FILES:
            products.update(START_VERSIONS)
        elif path in HOST_FILES or path.startswith(("assets/", "src/")) and not path.startswith("src/api/dashboard/static/"):
            products.add("host")
        elif path in CLIENT_FILES or path.startswith(("clients/macos/Sources/", "clients/macos/Resources/")):
            products.add("client")
    return products


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ("git", *args), cwd=repo, check=True, capture_output=True, text=True, errors="surrogateescape"
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise VersionPolicyError(f"Git 버전 이력을 읽을 수 없습니다. git {' '.join(args)}") from exc


def _ref(repo: Path, ref: str) -> str | None:
    result = subprocess.run(
        ("git", "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"),
        cwd=repo, capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    if result.returncode == 1:
        return None
    raise VersionPolicyError(f"Git 참조를 읽을 수 없습니다. {ref}")


def resolve_commit(repo: Path, commit: str) -> str:
    resolved = _ref(repo, commit)
    if not resolved:
        raise VersionPolicyError(f"빌드할 커밋을 찾을 수 없습니다. {commit}")
    return resolved


def changed_products(repo: Path, before: str, after: str) -> set[str]:
    return classify_paths(_git(repo, "diff", "--no-renames", "--name-only", "-z", before, after, "--").split("\0"))


def _one_product(products: set[str], subject: str) -> str | None:
    if len(products) > 1:
        raise VersionPolicyError(f"{subject}에 두 제품의 패키지 변경이 함께 있습니다. 제품별로 나누세요.")
    return next(iter(products), None)


def validate_commit_range(repo: Path, before: str, after: str) -> None:
    for commit in _git(repo, "rev-list", f"{before}..{after}").splitlines():
        _one_product(changed_products(repo, f"{commit}^1", commit), commit)


def _advance(version: str, event: str) -> str:
    major, minor, patch = map(int, version.split("."))
    if event == "major":
        return f"{major + 1}.0.0"
    if event == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _entry_version(commit: str, entry: dict) -> BuildVersion | None:
    product = entry["product"]
    return BuildVersion(product, entry["version"], commit, entry["version"]) if product else None


class VersionLedger:
    def __init__(self, repo: Path, *, state_path: Path | None = None) -> None:
        self.repo = Path(repo).resolve()
        if state_path is None:
            common_dir = _git(self.repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
            state_path = Path(common_dir).parent / "version.ledger.json"
        self.path = state_path

    def _main_histories(self, *, published: bool = False) -> Iterator[list[str]]:
        refs = ("refs/remotes/origin/main",) if published else ("refs/remotes/origin/main", "refs/heads/main")
        if not _ref(self.repo, refs[0]):
            refs = ("refs/heads/main",)
        for ref in refs:
            if _ref(self.repo, ref):
                yield _git(self.repo, "rev-list", "--first-parent", "--reverse", ref).splitlines()

    def _main_history(self, commit: str | None = None, *, published: bool = False) -> list[str]:
        for history in self._main_histories(published=published):
            if commit is None or commit in history:
                return history
        raise VersionPolicyError("지정한 커밋은 main 첫 부모 이력에 없습니다.")

    def _baseline(self, history: list[str], *, required: bool) -> str | None:
        starts = [_ref(self.repo, f"refs/tags/{tag}") for tag in START_TAGS.values()]
        if not any(starts) and not required:
            return None
        if None in starts or len(set(starts)) != 1 or starts[0] not in history:
            raise VersionPolicyError("두 시작 태그가 main의 같은 커밋을 가리켜야 합니다.")
        return starts[0]

    def require_baseline(self) -> str:
        baseline = self._baseline(self._main_history(published=True), required=True)
        assert baseline is not None
        return baseline

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"dev": {product: {} for product in START_VERSIONS}, "main": {}}
        except (OSError, ValueError) as exc:
            raise VersionPolicyError(f"{self.path.name} 버전 기록을 읽을 수 없습니다.") from exc
        if not isinstance(data, dict) or not isinstance(data.get("main"), dict) or not isinstance(data.get("dev"), dict):
            raise VersionPolicyError(f"{self.path.name} 버전 기록 형식이 올바르지 않습니다.")
        return data

    @contextmanager
    def _edit(self) -> Iterator[dict]:
        if sys.platform != "darwin":
            raise VersionPolicyError("버전 번호 발급은 맥에서 실행하세요.")
        import fcntl

        lock = self.path.with_suffix(".lock")
        with lock.open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            data = self._load()
            before = json.dumps(data)
            yield data
            if json.dumps(data) == before:
                return
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent, prefix=".version.ledger.", suffix=".tmp", delete=False
                ) as temp:
                    tmp = Path(temp.name)
                    json.dump(data, temp, indent=2)
                    temp.write("\n")
                    temp.flush()
                    os.fsync(temp.fileno())
                tmp.replace(self.path)
            finally:
                if tmp:
                    tmp.unlink(missing_ok=True)

    def _tags(self, history: list[str], baseline: str) -> dict[str, BuildVersion]:
        names = _git(self.repo, "for-each-ref", "--format=%(refname:strip=2)", "refs/tags/H", "refs/tags/C").splitlines()
        by_prefix = {prefix: product for product, prefix in TAG_PREFIX.items()}
        tags = {}
        eligible = set(history[history.index(baseline) + 1 :])
        for name in names:
            prefix, _, raw = name.partition("/v")
            if prefix not in by_prefix or not SEMVER.fullmatch(raw) or name in START_TAGS.values():
                continue
            commit = resolve_commit(self.repo, f"refs/tags/{name}")
            if commit not in eligible or commit in tags:
                raise VersionPolicyError(f"{name} 태그의 위치가 정식 버전 규칙과 다릅니다.")
            tags[commit] = BuildVersion(by_prefix[prefix], raw, commit, raw)
        return tags

    def _merge_kind(self, commit: str) -> tuple[str | None, re.Match[str] | None]:
        parents, _, message = _git(self.repo, "show", "-s", "--format=%P%x00%B", commit).partition("\0")
        markers = [marker for line in message.splitlines() if (marker := MERGE_MARKER.fullmatch(line))]
        if len(markers) > 1:
            raise VersionPolicyError(f"{commit}에 릴리즈 병합 표기가 여러 개 있습니다.")
        return ("merge" if len(parents.split()) > 1 else None, markers[0] if markers else None)

    def _record_through(
        self, data: dict, history: list[str], baseline: str, commit: str,
        event: str, expected_product: str | None,
    ) -> BuildVersion | None:
        entries = data["main"]
        versions = START_VERSIONS.copy()
        tags = self._tags(history, baseline)
        nodes = history[history.index(baseline) : history.index(commit) + 1]
        result = None
        for before, node in zip(nodes, nodes[1:]):
            requested = event if node == commit else None
            tagged = tags.get(node)
            if node in entries:
                record = entries[node]
                if requested and record["event"] != requested:
                    raise VersionPolicyError(f"{node}의 기록된 버전업 유형이 요청과 다릅니다.")
                result = _entry_version(node, record)
                if tagged and result != tagged:
                    raise VersionPolicyError(f"{node}의 정식 태그와 버전 기록이 다릅니다.")
            else:
                product = _one_product(changed_products(self.repo, before, node), node)
                merge, marker = self._merge_kind(node)
                if marker and product and marker[1] != product:
                    raise VersionPolicyError(f"{node}의 릴리즈 병합 표기와 실제 변경 제품이 다릅니다.")
                if tagged:
                    kind = marker[2] if marker else ("major" if tagged.version.endswith(".0.0") else "minor")
                    if requested and kind != requested:
                        raise VersionPolicyError(f"{node}의 정식 태그와 요청한 버전업 유형이 다릅니다.")
                elif merge or marker:
                    if requested is None and product is None and marker:
                        kind = marker[2]
                    elif not merge or not marker or requested != marker[2]:
                        raise VersionPolicyError(f"{node}의 PR 병합 릴리즈를 먼저 재개하세요.")
                    else:
                        kind = requested
                elif requested in ("minor", "major"):
                    raise VersionPolicyError("마이너·메이저는 전용 명령으로 병합한 PR 커밋에만 부여합니다.")
                else:
                    kind = "patch"
                version = _advance(versions[product], kind) if product else None
                result = BuildVersion(product, version, node, version) if product else None
                if tagged and result != tagged:
                    raise VersionPolicyError(f"{node}의 정식 태그가 제품 이력의 다음 버전과 다릅니다.")
                entries[node] = {"event": kind, "product": product, "version": version}
            if result:
                versions[result.product] = result.version
        if expected_product is not None and (not result or result.product != expected_product):
            raise VersionPolicyError("예상 제품과 main에서 변경한 제품이 다릅니다.")
        return result

    def record_main(
        self, commit: str, *, event: str, expected_product: str | None = None, major_approved: bool = False,
    ) -> BuildVersion | None:
        if event not in ("patch", "minor", "major"):
            raise VersionPolicyError("버전업 유형은 patch, minor, major 중 하나여야 합니다.")
        if event == "major" and not major_approved:
            raise VersionPolicyError("메이저 버전업은 사용자의 명시적 승인이 필요합니다.")
        commit = resolve_commit(self.repo, commit)
        history = self._main_history(commit, published=event != "patch")
        baseline = self.require_baseline()
        if baseline not in history or history.index(commit) <= history.index(baseline):
            raise VersionPolicyError("시작 태그 이후의 main 커밋만 새 버전을 부여할 수 있습니다.")
        with self._edit() as data:
            return self._record_through(data, history, baseline, commit, event, expected_product)

    def read_main(self, commit: str) -> tuple[str, BuildVersion | None] | None:
        commit = resolve_commit(self.repo, commit)
        entry = self._load()["main"].get(commit)
        return (entry["event"], _entry_version(commit, entry)) if entry else None

    def _known_main(self, product: str, commit: str, history: list[str], baseline: str) -> BuildVersion:
        entries = self._load()["main"]
        tags = self._tags(history, baseline)
        for node in reversed(history[history.index(baseline) + 1 : history.index(commit) + 1]):
            entry = entries.get(node)
            assigned = _entry_version(node, entry) if entry else tags.get(node)
            if assigned and assigned.product == product:
                return replace(assigned, commit=commit)
        initial = START_VERSIONS[product]
        return BuildVersion(product, initial, commit, initial)

    def _dev_commits(self, commit: str, main: str) -> list[str]:
        fork = _git(self.repo, "merge-base", main, commit).strip()
        return _git(self.repo, "rev-list", "--first-parent", "--reverse", f"{fork}..{commit}").splitlines()

    def _known_dev(self, product: str, commit: str, versions: dict) -> BuildVersion | None:
        for node in _git(self.repo, "rev-list", "--first-parent", commit).splitlines():
            if node in versions:
                return BuildVersion(product, **versions[node], commit=commit)
        return None

    def allocate_dev(self, product: str, commit: str) -> BuildVersion:
        self._validate_product(product)
        commit = resolve_commit(self.repo, commit)
        histories = list(self._main_histories())
        if not histories:
            raise VersionPolicyError("main 브랜치를 찾을 수 없습니다.")
        if any(commit in history for history in histories):
            raise VersionPolicyError("main 커밋에는 개발 버전을 부여할 수 없습니다.")
        history = histories[0]
        baseline = self._baseline(history, required=False)
        with self._edit() as data:
            versions = data["dev"][product]
            next_number = len(versions) + 1
            base = START_VERSIONS[product]
            if baseline:
                fork = _git(self.repo, "merge-base", history[-1], commit).strip()
                if fork in history[history.index(baseline) :]:
                    base = self._known_main(product, fork, history, baseline).version
            for node in self._dev_commits(commit, history[-1]):
                products = changed_products(self.repo, f"{node}^1", node)
                if baseline:
                    _one_product(products, node)
                if product in products and node not in versions:
                    versions[node] = {"version": f"dev.{next_number}", "base_version": base}
                    next_number += 1
            assigned = self._known_dev(product, commit, versions)
            if not assigned:
                raise VersionPolicyError("이 브랜치에 해당 제품의 버전을 부여할 패키지 변경이 없습니다.")
            return assigned

    @staticmethod
    def _validate_product(product: str) -> None:
        if product not in START_VERSIONS:
            raise VersionPolicyError(f"알 수 없는 빌드 제품입니다. {product}")

    def get(self, product: str, commit: str) -> BuildVersion | None:
        self._validate_product(product)
        commit = resolve_commit(self.repo, commit)
        for history in self._main_histories():
            if commit in history:
                baseline = self._baseline(history, required=False)
                if not baseline or history.index(commit) < history.index(baseline):
                    return None
                return self._known_main(product, commit, history, baseline)
        return self._known_dev(product, commit, self._load()["dev"][product])

    def resolve_build(
        self, product: str, commit: str, *, development: bool | None = None,
    ) -> BuildVersion:
        self._validate_product(product)
        commit = resolve_commit(self.repo, commit)
        if development is None:
            development = _git(self.repo, "branch", "--show-current").strip() != "main"
        if development:
            return self.allocate_dev(product, commit)
        baseline = self.require_baseline()
        history = self._main_history(commit)
        if commit != baseline:
            entry = self.read_main(commit)
            if entry is None:
                tag = self._tags(history, baseline).get(commit)
                if tag:
                    _, marker = self._merge_kind(commit)
                    kind = marker[2] if marker else ("major" if tag.version.endswith(".0.0") else "minor")
                    self.record_main(commit, event=kind, major_approved=True)
                else:
                    self.record_main(commit, event="patch")
        return self._known_main(product, commit, history, baseline)


def main() -> int:
    parser = argparse.ArgumentParser(description="스테이징한 제품 변경을 검사합니다.")
    parser.add_argument("command", choices=("check-staged",))
    parser.parse_args()
    try:
        repo = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
        # The new product rule starts at the agreed two-tag baseline.
        if not any(_ref(repo, f"refs/tags/{tag}") for tag in START_TAGS.values()):
            return 0
        VersionLedger(repo).require_baseline()
        staged = _git(repo, "diff", "--cached", "--no-renames", "--name-only", "-z", "--")
        _one_product(classify_paths(staged.split("\0")), "스테이징한 커밋")
    except VersionPolicyError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
