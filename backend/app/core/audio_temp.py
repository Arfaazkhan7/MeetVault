"""
MeetVault Audio Temp Management & Crash Recovery.

Audits and controls temporary disk audio storage across MeetVault:
- Dedicated, application-controlled temporary directory.
- Strict filename prefixes and path traversal prevention.
- Safe lifecycle management with context managers.
- Active in-flight file registry to prevent premature deletion during processing.
- Stale file crash recovery based on age limits (TTL).
- Safe file ownership/containment verification (never deletes outside dedicated dir).
- Sanitized logging without exposing audio data, tokens, or credentials.
"""

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Generator, Optional, Union
import uuid

from app.core.config import settings

logger = logging.getLogger("audio_temp_manager")

AUDIO_TEMP_PREFIX = "mv_audio_"
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".bin", ".pcm"}
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")

_active_temp_files: set[Path] = set()
_active_files_lock = threading.Lock()


def get_audio_temp_dir() -> Path:
    """
    Return the dedicated, application-controlled temporary audio directory.
    Creates it if it does not already exist with restricted permissions (0o700).
    """
    if settings.AUDIO_TEMP_DIR:
        base_dir = Path(settings.AUDIO_TEMP_DIR)
    else:
        import tempfile
        base_dir = Path(tempfile.gettempdir()) / "meetvault_audio_temp"

    try:
        base_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    except Exception as exc:
        logger.error("[AUDIO_TEMP_INIT_ERROR] Could not create temp dir %s: %s", base_dir, exc)
    return base_dir.resolve()


def _sanitize_filename(filename: str) -> str:
    """Format filename safely for logs without leaking raw paths or data."""
    if not filename:
        return "none"
    name = Path(filename).name
    # Keep only prefix and tail if long
    if len(name) > 32:
        return f"{name[:14]}...{name[-12:]}"
    return name


def validate_temp_audio_path(path: Union[str, Path]) -> Path:
    """
    Strictly validate that a path resides within MeetVault's dedicated audio temp directory.
    Prevents path traversal attempts (e.g. '../', root paths, or arbitrary file deletions).
    Rejects targets outside the dedicated directory or targets that are the directory itself.
    """
    if not path:
        raise ValueError("Audio temp path cannot be empty")

    temp_dir = get_audio_temp_dir()
    resolved = Path(path).resolve()

    if resolved == temp_dir:
        raise ValueError("Operation target cannot be the temporary root directory itself")

    try:
        is_contained = resolved.is_relative_to(temp_dir)
    except AttributeError:
        # Python < 3.9 fallback
        try:
            resolved.relative_to(temp_dir)
            is_contained = True
        except ValueError:
            is_contained = False

    if not is_contained:
        raise ValueError(f"Path traversal security violation: {path} is outside dedicated audio temp directory")

    filename = resolved.name
    if not (filename.startswith(AUDIO_TEMP_PREFIX) or filename.startswith("recording_")):
        raise ValueError(f"Invalid temporary audio filename pattern: {filename}")

    return resolved


def register_active_temp_file(path: Union[str, Path]) -> Path:
    """Register a temporary audio file as actively being read or written."""
    resolved = validate_temp_audio_path(path)
    with _active_files_lock:
        _active_temp_files.add(resolved)
    return resolved


def unregister_active_temp_file(path: Union[str, Path]) -> None:
    """Unregister an active temporary audio file."""
    try:
        resolved = Path(path).resolve()
        with _active_files_lock:
            _active_temp_files.discard(resolved)
    except Exception:
        pass


def is_temp_file_active(path: Union[str, Path]) -> bool:
    """Check whether a temporary audio file is currently registered as active."""
    try:
        resolved = Path(path).resolve()
        with _active_files_lock:
            return resolved in _active_temp_files
    except Exception:
        return False


def create_temp_audio_file(
    *,
    suffix: str = ".wav",
    prefix: str = AUDIO_TEMP_PREFIX,
    meeting_id: Optional[str] = None,
    content: Optional[bytes] = None,
) -> Path:
    """
    Create a managed temporary audio file in the dedicated directory.
    Registers the file in active processing registry.
    """
    clean_suffix = suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
    if clean_suffix not in ALLOWED_EXTENSIONS:
        clean_suffix = ".wav"

    safe_mtg = "general"
    if meeting_id:
        cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "", meeting_id)
        if cleaned:
            safe_mtg = cleaned[:32]

    unique_id = uuid.uuid4().hex[:12]
    ts = int(time.time())
    clean_prefix = prefix if prefix.startswith(AUDIO_TEMP_PREFIX) or prefix.startswith("recording_") else AUDIO_TEMP_PREFIX
    filename = f"{clean_prefix}{safe_mtg}_{unique_id}_{ts}{clean_suffix}"

    temp_dir = get_audio_temp_dir()
    file_path = (temp_dir / filename).resolve()

    if content is not None:
        with open(file_path, "wb") as f:
            f.write(content)
            f.flush()
    else:
        file_path.touch(mode=0o600, exist_ok=False)

    register_active_temp_file(file_path)
    logger.debug("[TEMP_AUDIO_CREATED] file=%s size=%d", _sanitize_filename(filename), len(content) if content else 0)
    return file_path


@contextmanager
def managed_temp_audio_file(
    *,
    suffix: str = ".wav",
    prefix: str = AUDIO_TEMP_PREFIX,
    meeting_id: Optional[str] = None,
    content: Optional[bytes] = None,
) -> Generator[Path, None, None]:
    """
    Context manager for short-lived audio files.
    Guarantees deletion in finally block upon normal completion or unhandled exception.
    """
    temp_file = create_temp_audio_file(
        suffix=suffix,
        prefix=prefix,
        meeting_id=meeting_id,
        content=content,
    )
    try:
        yield temp_file
    finally:
        safe_delete_temp_file(temp_file, reason="managed_context_exit")


def safe_delete_temp_file(
    path: Union[str, Path, None],
    reason: str = "normal_cleanup",
) -> bool:
    """
    Safely delete a temporary audio file after validating containment.
    Never deletes files outside MeetVault's dedicated temporary directory.
    Returns True if the file does not exist (idempotent) or was successfully unlinked.
    """
    if path is None:
        return True

    try:
        resolved = validate_temp_audio_path(path)
    except ValueError as val_err:
        logger.error("[TEMP_AUDIO_SECURITY_BLOCK] Refusing deletion for invalid path %s: %s", path, val_err)
        return False

    unregister_active_temp_file(resolved)

    if not resolved.exists():
        return True

    try:
        resolved.unlink(missing_ok=True)
        if not resolved.exists():
            logger.info("[TEMP_AUDIO_DELETED] file=%s reason=%s", _sanitize_filename(resolved.name), reason)
            return True
        else:
            logger.warning("[TEMP_AUDIO_DELETE_FAILED] File still exists after unlink: %s", _sanitize_filename(resolved.name))
            return False
    except Exception as exc:
        logger.warning(
            "[TEMP_AUDIO_DELETE_ERROR] Could not unlink %s (%s): %s",
            _sanitize_filename(resolved.name),
            reason,
            exc,
        )
        return False


def recover_and_cleanup_stale_temp_audio(
    max_age_minutes: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """
    Crash recovery scanner for stale temporary audio files left by process termination or crashes.
    Scans the dedicated temporary directory and removes files older than max_age_minutes.
    Guarantees:
      - Never touches files outside dedicated directory.
      - Skips files currently registered in active processing.
      - Skips files younger than max_age_minutes.
      - Never touches non-MeetVault files.
    """
    if max_age_minutes is None:
        max_age_minutes = getattr(settings, "AUDIO_TEMP_MAX_AGE_MINUTES", 30) or 30

    temp_dir = get_audio_temp_dir()
    cutoff_time = time.time() - (max_age_minutes * 60)

    stats = {
        "scanned": 0,
        "deleted": 0,
        "skipped_active": 0,
        "skipped_young": 0,
        "failed": 0,
        "temp_dir": str(temp_dir),
    }

    if not temp_dir.exists():
        return stats

    try:
        entries = list(temp_dir.iterdir())
    except Exception as exc:
        logger.error("[STALE_CLEANUP_SCAN_ERROR] Could not list temp dir %s: %s", temp_dir, exc)
        return stats

    for entry in entries:
        if not entry.is_file():
            continue

        filename = entry.name
        if not (filename.startswith(AUDIO_TEMP_PREFIX) or filename.startswith("recording_")):
            # Unrelated file: never touch
            continue

        stats["scanned"] += 1

        # Check if actively registered
        if is_temp_file_active(entry):
            stats["skipped_active"] += 1
            logger.debug("[STALE_CLEANUP_SKIP_ACTIVE] file=%s is currently in-flight", _sanitize_filename(filename))
            continue

        try:
            mtime = entry.stat().st_mtime
            if mtime > cutoff_time:
                stats["skipped_young"] += 1
                continue

            # Stale file candidate: process crashed or task abandoned
            if dry_run:
                stats["deleted"] += 1
                logger.info("[STALE_CLEANUP_DRY_RUN] Would delete stale file %s (age=%.1fm)", _sanitize_filename(filename), (time.time() - mtime) / 60)
            else:
                success = safe_delete_temp_file(entry, reason="crash_recovery_stale")
                if success:
                    stats["deleted"] += 1
                else:
                    stats["failed"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning("[STALE_CLEANUP_FILE_ERROR] Error checking %s: %s", _sanitize_filename(filename), exc)

    logger.info(
        "[STALE_TEMP_CLEANUP_COMPLETE] scanned=%d deleted=%d active_skipped=%d young_skipped=%d failed=%d",
        stats["scanned"],
        stats["deleted"],
        stats["skipped_active"],
        stats["skipped_young"],
        stats["failed"],
    )
    return stats
