"""가상 사례 3종(정상·차이·자료 부족)을 DB에 넣는다. 사용: python scripts/seed_samples.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import records, samples  # noqa: E402

if __name__ == "__main__":
    existing = {c["name"] for c in records.tree()}
    if any(name in existing for name, _ in samples.CASES):
        print("가상 사례가 이미 있습니다. 다시 넣으려면 data/audit.db를 지우세요.")
        sys.exit(0)
    ids = samples.seed()
    print("가상 사례 조서:", ids, "→", records.db_path())
