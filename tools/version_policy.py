"""Version allocation on the Mac and the immutable input consumed by native builders."""

from __future__ import annotations

import argparse
import ast
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
BUILD_SCRIPT = "build.py"
SHARED_FILES = {BUILD_SCRIPT, "assets/icons/app/app_icon.png"}
BUILD_HOST_DEFINITIONS = {
    "WINDOWS_VERSION_FILE", "DASHBOARD_FRONTEND_DIR", "DASHBOARD_STATIC_BUILD_DIR", "DASHBOARD_CACHE_DIR",
    "SPEC_FILE", "APP_NAME", "APP_FOLDER", "INNO_SETUP_PATH", "INSTALLER_SCRIPT", "WINDOWS_PYTHON_VERSION",
    "WINDOWS_REQUIRED_DISTRIBUTIONS", "CERT_DIR", "CERT_THUMBPRINT_FILE",
    "bootstrap_windows_build_runtime", "installed_distribution_versions", "validate_windows_build_runtime",
    "load_windows_version_info", "windows_package_paths", "build_dashboard_frontend", "build_with_pyinstaller",
    "find_signtool", "sign_file", "sign_build_artifacts", "create_zip_distribution",
    "windows_installer_output_base", "create_inno_setup_command", "create_installer", "run_windows_build",
}
BUILD_CLIENT_DEFINITIONS = {
    "MACOS_PACKAGE_TOOL", "MACOS_CLIENT_DIR", "MACOS_APP_NAME", "MACOS_APP_BUNDLE", "MACOS_SWIFT_RELEASE_EXECUTABLE",
    "MACOS_APP_EXECUTABLE", "MACOS_APP_PROCESS_NAME", "MACOS_PKG_SCRIPTS_DIR", "MACOS_CODESIGN_IDENTITY_ENV",
    "MACOS_DEFAULT_CODESIGN_IDENTITY", "load_macos_version_info", "macos_pkg_path", "macos_pkg_preinstall_script",
    "prepare_macos_pkg_scripts_dir", "create_pkgbuild_command", "macos_codesign_identity",
    "resolve_macos_codesign_identity", "macos_codesign_identity_available", "create_macos_app_bundle_command",
    "build_macos_remote_app", "create_macos_pkg", "run_macos_build",
}
BUILD_ARCHIVE_DEFINITIONS = {
    "ARCHIVES_DIR", "VERSION_ID", "VERSIONED_PACKAGE_NAME", "WINDOWS_ARCHIVE_ID", "WINDOWS_PACKAGE_PAIR",
    "artifact_archive_bucket", "iter_release_artifacts_for_archive", "prune_archive_files", "archive_old_files",
    "_complete_windows_pair", "_archive_windows_pair", "_windows_setup_signature_valid", "_restorable_windows_pair",
}


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


def _git_result(repo: Path, *args: str, allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ("git", *args), cwd=repo, check=False, capture_output=True, text=True, errors="surrogateescape"
        )
    except OSError as exc:
        raise VersionPolicyError(f"Git 버전 이력을 읽을 수 없습니다. git {' '.join(args)}") from exc
    if result.returncode not in allowed:
        raise VersionPolicyError(f"Git 버전 이력을 읽을 수 없습니다. git {' '.join(args)}")
    return result


def _git(repo: Path, *args: str) -> str:
    return _git_result(repo, *args).stdout


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


def _build_definition_scope(node: ast.stmt) -> tuple[str, str | None]:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.decorator_list:
        name = node.name
    elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
    elif isinstance(node, ast.Import) and [(alias.name, alias.asname) for alias in node.names] == [("tempfile", None)]:
        return "archive", None
    else:
        return "shared", None
    if name in BUILD_HOST_DEFINITIONS:
        return "host", name
    if name in BUILD_CLIENT_DEFINITIONS:
        return "client", name
    if name in BUILD_ARCHIVE_DEFINITIONS:
        return "archive", name
    return "shared", None


def _build_sections(repo: Path, tree: str) -> list[tuple[str, str, str]] | None:
    blob = _git_result(repo, "cat-file", "blob", f"{tree}:{BUILD_SCRIPT}", allowed=(0, 128))
    if blob.returncode:
        return None
    try:
        nodes = ast.parse(blob.stdout).body
    except (SyntaxError, ValueError):
        return None
    sections = []
    for node in nodes:
        scope, name = _build_definition_scope(node)
        if scope != "archive":
            body = ast.dump(node)
            sections.append((scope, name or body, body))
    return sections


def _scope_positions(
    sections: list[tuple[str, str, str]], common: set[tuple[str, str]],
) -> dict[tuple[str, str], list[set[tuple[str, str]]]]:
    """Keep the relative order of surviving definitions across scope boundaries."""
    positions: dict[tuple[str, str], list[set[tuple[str, str]]]] = {}
    earlier: set[tuple[str, str]] = set()
    for scope, name, _ in sections:
        key = (scope, name)
        if key in common:
            positions.setdefault(key, []).append({other for other in earlier if other[0] != scope})
            earlier.add(key)
    return positions


def _build_products(
    left: list[tuple[str, str, str]] | None, right: list[tuple[str, str, str]] | None,
) -> set[str]:
    if left is None or right is None:
        return set(START_VERSIONS)
    if left == right:
        return set()
    left_bodies = {scope: [body for owner, _, body in left if scope == owner] for scope in (*START_VERSIONS, "shared")}
    right_bodies = {scope: [body for owner, _, body in right if scope == owner] for scope in (*START_VERSIONS, "shared")}
    common = {(scope, name) for scope, name, _ in left} & {(scope, name) for scope, name, _ in right}
    if left_bodies["shared"] != right_bodies["shared"] or _scope_positions(left, common) != _scope_positions(right, common):
        return set(START_VERSIONS)
    return {product for product in START_VERSIONS if left_bodies[product] != right_bodies[product]}


def _diff_products(
    repo: Path, paths: Iterable[str], before: str, after: str, *, build_projections: tuple[str, ...] = (),
) -> set[str]:
    paths = set(paths)
    products = classify_paths(paths - {BUILD_SCRIPT})
    if BUILD_SCRIPT in paths:
        actual = _build_sections(repo, after)
        for projected in build_projections or (before,):
            products.update(_build_products(_build_sections(repo, projected), actual))
    return products


def changed_products(repo: Path, before: str, after: str) -> set[str]:
    paths = _git(repo, "diff", "--no-renames", "--name-only", "-z", before, after, "--").split("\0")
    return _diff_products(repo, paths, before, after)


def _one_product(products: set[str], subject: str) -> str | None:
    if len(products) > 1:
        raise VersionPolicyError(f"{subject}에 두 제품의 패키지 변경이 함께 있습니다. 제품별로 나누세요.")
    return next(iter(products), None)


def _is_main_sync(repo: Path, side_parents: list[str], main_tips: tuple[str, ...]) -> bool:
    imported_main = any(
        _git_result(repo, "merge-base", "--is-ancestor", parent, main, allowed=(0, 1)).returncode == 0
        for parent in side_parents
        for main in main_tips
    )
    if imported_main and len(side_parents) != 1:
        raise VersionPolicyError("main 동기화와 다른 브랜치 병합은 서로 다른 커밋으로 나누세요.")
    return imported_main


def _automatic_merge_tree(repo: Path, first: str, second: str, *options: str) -> tuple[str, set[str]]:
    result = _git_result(
        repo, "merge-tree", "--write-tree", "--no-messages", "--name-only", "-z", *options, first, second, allowed=(0, 1),
    )
    tree, *paths = result.stdout.split("\0")
    if not COMMIT.fullmatch(tree):
        raise VersionPolicyError("main 동기화의 자동 병합 트리를 확인할 수 없습니다.")
    return tree, {path for path in paths if path}


def _main_sync_products(repo: Path, first: str, second: str, after: str) -> set[str]:
    automatic, conflicts = _automatic_merge_tree(repo, first, second)
    revisions = (automatic, after) if after else ("--cached", automatic)
    paths = set(_git(repo, "diff", "--no-renames", "--name-only", "-z", *revisions, "--").split("\0"))
    projections: tuple[str, ...] = ()
    if BUILD_SCRIPT in conflicts:
        # Git preserves the automatic, non-conflicting edits in both projections.
        try:
            alternatives = [_automatic_merge_tree(repo, first, second, "-X", side) for side in ("ours", "theirs")]
        except VersionPolicyError as exc:
            raise VersionPolicyError("현재 Git으로 build.py 충돌의 두 병합 결과를 재현할 수 없습니다.") from exc
        if any(BUILD_SCRIPT in unresolved for _, unresolved in alternatives):
            return set(START_VERSIONS)
        projections = tuple(tree for tree, _ in alternatives)
    return _diff_products(repo, paths | conflicts, automatic, after, build_projections=projections)


def _commit_products(repo: Path, commit: str, main_tips: tuple[str, ...]) -> set[str]:
    parents = _git(repo, "show", "-s", "--format=%P", commit).split()
    if _is_main_sync(repo, parents[1:], main_tips):
        return _main_sync_products(repo, *parents, commit)
    return changed_products(repo, parents[0], commit)


def validate_commit_range(repo: Path, before: str, after: str) -> None:
    for commit in _git(repo, "rev-list", f"{before}..{after}").splitlines():
        _one_product(_commit_products(repo, commit, (before,)), commit)


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
        event: str | None, expected_product: str | None, *, require_prior_tags: bool = False,
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
                if require_prior_tags and result and record["event"] != "patch" and not tagged:
                    raise VersionPolicyError(f"{node}의 PR 병합 릴리즈를 먼저 재개하세요.")
            else:
                product = _one_product(changed_products(self.repo, before, node), node)
                merge, marker = self._merge_kind(node)
                if marker and product and marker[1] != product:
                    raise VersionPolicyError(f"{node}의 릴리즈 병합 표기와 실제 변경 제품이 다릅니다.")
                if tagged:
                    kind = marker[2] if marker else ("major" if tagged.version.endswith(".0.0") else "minor")
                    if requested and kind != requested:
                        raise VersionPolicyError(f"{node}의 정식 태그와 요청한 버전업 유형이 다릅니다.")
                elif product is None and requested in (None, "patch"):
                    kind = marker[2] if merge and marker else "patch"
                elif merge or marker:
                    if not merge or not marker or requested != marker[2]:
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

    def check_main_ready(self, commit: str) -> None:
        """Check for unresolved previous product merges without recording any versions."""
        commit = resolve_commit(self.repo, commit)
        history = self._main_history(commit, published=True)
        baseline = self.require_baseline()
        if history.index(commit) < history.index(baseline):
            raise VersionPolicyError("시작 태그 이후의 main만 새 PR을 병합할 수 있습니다.")
        self._record_through(self._load(), history, baseline, commit, None, None, require_prior_tags=True)

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
        main_tips = tuple(dict.fromkeys(branch_history[-1] for branch_history in histories))
        baseline = self._baseline(history, required=False)
        with self._edit() as data:
            versions = data["dev"][product]
            next_number = len(versions) + 1
            base = START_VERSIONS[product]
            if baseline:
                fork = _git(self.repo, "merge-base", history[-1], commit).strip()
                if fork in history[history.index(baseline) :]:
                    base = self._known_main(product, fork, history, baseline).version
            for node in _git(self.repo, "rev-list", "--first-parent", "--reverse", commit, "--not", *main_tips).splitlines():
                products = _commit_products(self.repo, node, main_tips)
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
        ledger = VersionLedger(repo)
        ledger.require_baseline()
        merge_head_path = repo / _git(repo, "rev-parse", "--git-path", "MERGE_HEAD").strip()
        parents = merge_head_path.read_text(encoding="ascii").split() if merge_head_path.is_file() else []
        main_tips = tuple(history[-1] for history in ledger._main_histories())
        if _is_main_sync(repo, parents, main_tips):
            products = _main_sync_products(repo, "HEAD", parents[0], "")
        else:
            staged = _git(repo, "diff", "--cached", "--no-renames", "--name-only", "-z", "HEAD", "--")
            products = _diff_products(repo, staged.split("\0"), "HEAD", "")
        _one_product(products, "스테이징한 커밋")
    except VersionPolicyError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
