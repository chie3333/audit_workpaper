import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import content, records  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_WP_DB", str(tmp_path / "test.db"))
    yield tmp_path / "test.db"


@pytest.fixture
def tmp_content(tmp_path, monkeypatch):
    """콘텐츠 폴더 사본. 수정해도 원본은 그대로."""
    dst = tmp_path / "content"
    shutil.copytree(ROOT / "content", dst)
    monkeypatch.setattr(content, "CONTENT_DIR", dst)
    return dst


@pytest.fixture
def resolved():
    return content.resolve("cash.schedule_recon")


@pytest.fixture
def seeded():
    from app import samples
    return samples.seed()


def load(wid, rev=None):
    return records.load_workpaper(wid, rev)
