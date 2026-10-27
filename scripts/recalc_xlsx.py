"""LibreOffice로 엑셀 수식을 다시 계산한 사본을 만든다(테스트용).

사용: python scripts/recalc_xlsx.py 입력.xlsx 출력폴더
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def recalc(src: Path, out_dir: Path, timeout: int = 90) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice(soffice)가 없어 엑셀 수식을 계산할 수 없음")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        cmd = [soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--calc",
               "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out_dir), str(src)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
    out = out_dir / src.name
    if not out.exists():
        raise RuntimeError("LibreOffice 변환 결과가 없음")
    return out


if __name__ == "__main__":
    print(recalc(Path(sys.argv[1]), Path(sys.argv[2])))
