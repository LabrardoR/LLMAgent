from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "app"
DATA_ROOT = APP_ROOT / "data"
ASSET_ROOT = DATA_ROOT / "assets"
AVATAR_ROOT = ASSET_ROOT / "avatars"
UPLOAD_ROOT = DATA_ROOT / "uploads"
VECTOR_ROOT = DATA_ROOT / "faiss"

_KNOWN_DIRS = (
    DATA_ROOT,
    ASSET_ROOT,
    AVATAR_ROOT,
    UPLOAD_ROOT,
    VECTOR_ROOT,
)


def _migrate_legacy_avatars() -> None:
    legacy_avatar_dir = APP_ROOT / "static" / "avatars"
    if not legacy_avatar_dir.exists():
        return

    for file_path in legacy_avatar_dir.glob("*"):
        if not file_path.is_file():
            continue
        target_path = AVATAR_ROOT / file_path.name
        if target_path.exists():
            continue
        shutil.move(str(file_path), str(target_path))


def ensure_storage_dirs() -> None:
    for path in _KNOWN_DIRS:
        path.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_avatars()


def make_unique_filename(original_name: str, fallback_ext: str = ".bin") -> str:
    ext = Path(original_name or "").suffix.lower()
    if not ext:
        ext = fallback_ext
    if not ext.startswith("."):
        ext = f".{ext}"
    return f"{uuid.uuid4().hex}{ext}"


def user_avatar_dir(user_id: str) -> Path:
    path = AVATAR_ROOT / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_upload_dir(user_id: str) -> Path:
    path = UPLOAD_ROOT / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_asset_url(*parts: str) -> str:
    cleaned = [quote(str(part).strip("/\\")) for part in parts if str(part).strip("/\\")]
    return "/assets/" + "/".join(cleaned)


def build_upload_url(*parts: str) -> str:
    cleaned = [quote(str(part).strip("/\\")) for part in parts if str(part).strip("/\\")]
    return "/uploads/" + "/".join(cleaned)


def to_data_relative_path(path: Path) -> str:
    return path.resolve().relative_to(DATA_ROOT.resolve()).as_posix()


def resolve_data_path(stored_path: str) -> Path:
    raw = Path(stored_path)
    candidates: list[Path] = []

    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(DATA_ROOT / raw)
        candidates.append(PROJECT_ROOT / raw)

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(DATA_ROOT.resolve())
            return resolved
        except Exception:
            continue

    raise ValueError("invalid_storage_path")


def is_path_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def safe_unlink(path: Path, root: Path | None = None) -> None:
    if not path.exists() or not path.is_file():
        return
    if root and not is_path_within(root, path):
        return
    path.unlink()


def detect_content_type(file_name: str) -> str:
    content_type, _ = mimetypes.guess_type(file_name)
    return content_type or "application/octet-stream"
