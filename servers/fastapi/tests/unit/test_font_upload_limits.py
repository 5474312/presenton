import asyncio
import io
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from utils import font_uploads


@pytest.fixture
def fonts_dir(tmp_path, monkeypatch):
    directory = tmp_path / "fonts"
    directory.mkdir()
    monkeypatch.setattr(font_uploads, "get_fonts_directory", lambda: str(directory))
    return directory


def test_raise_if_font_upload_too_large_rejects_over_limit():
    with pytest.raises(HTTPException) as exc:
        font_uploads.raise_if_font_upload_too_large(
            font_uploads.MAX_FONT_UPLOAD_BYTES + 1
        )
    assert exc.value.status_code == 413


def test_raise_if_font_upload_too_large_allows_at_limit():
    font_uploads.raise_if_font_upload_too_large(font_uploads.MAX_FONT_UPLOAD_BYTES)
    font_uploads.raise_if_font_upload_too_large(None)


def test_read_upload_with_size_limit_streams_and_enforces_cap(monkeypatch):
    monkeypatch.setattr(font_uploads, "MAX_FONT_UPLOAD_BYTES", 64)
    oversized = b"a" * 65
    upload = UploadFile(filename="big.ttf", file=io.BytesIO(oversized))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(font_uploads.read_upload_with_size_limit(upload))

    assert exc.value.status_code == 413


def test_persist_upload_file_rejects_oversized_without_writing(fonts_dir, monkeypatch):
    monkeypatch.setattr(font_uploads, "MAX_FONT_UPLOAD_BYTES", 32)
    oversized = b"x" * 64
    upload = UploadFile(
        filename="HugeFont.ttf",
        file=io.BytesIO(oversized),
        size=len(oversized),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(font_uploads.persist_upload_file(upload))

    assert exc.value.status_code == 413
    assert list(fonts_dir.iterdir()) == []


def test_persist_upload_file_removes_orphan_after_invalid_font(fonts_dir):
    upload = UploadFile(
        filename="Broken.ttf",
        file=io.BytesIO(b"not-a-real-font"),
        size=14,
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(font_uploads.persist_upload_file(upload))

    assert exc.value.status_code == 400
    assert list(fonts_dir.iterdir()) == []


def test_persist_upload_file_keeps_valid_font_and_persists(fonts_dir):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    source = os.path.join(
        repo_root, "templates", "momentum", "static", "Lato Regular.ttf"
    )
    if not os.path.isfile(source):
        pytest.skip("No sample TTF available in workspace")

    with open(source, "rb") as handle:
        payload = handle.read()

    upload = UploadFile(
        filename="Lato Regular.ttf",
        file=io.BytesIO(payload),
        size=len(payload),
    )

    fake_upload = MagicMock()
    fake_upload.id = "font-id"
    fake_session = MagicMock()
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.refresh = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    with patch.object(
        font_uploads,
        "_build_font_upload_from_path",
        return_value=fake_upload,
    ), patch.object(
        font_uploads,
        "async_session_maker",
        return_value=fake_session,
    ):
        font_upload, dest_path = asyncio.run(
            font_uploads.persist_upload_file(upload)
        )

    assert font_upload is fake_upload
    assert os.path.isfile(dest_path)
    assert dest_path.startswith(str(fonts_dir))
    assert os.path.getsize(dest_path) == len(payload)
    fake_session.add.assert_called_once_with(fake_upload)
