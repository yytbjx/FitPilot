"""七层评估：文档解析层（Layer 1）。"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.eval.common import PassRateEvalResult
from app.eval.progress import track_cases
from app.rag.parsing import parse_file_rich, supported_suffixes


@dataclass
class ParsingEvalResult(PassRateEvalResult):
    min_pass_rate: float = 0.9
    label: str = "Parsing Eval"


def run_parsing_eval(suite_path: Path) -> ParsingEvalResult:
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    result = ParsingEvalResult(min_pass_rate=float(raw.get("min_pass_rate") or 0.9))
    cases = list(raw.get("cases") or [])
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for case in track_cases(cases, desc="parsing"):
            suffix = str(case.get("suffix") or ".txt")
            content = str(case.get("content") or "")
            min_chars = int(case.get("min_chars") or 1)
            expect_title = case.get("expect_title_contains")
            path = tmp_dir / f"{case.get('id', 'case')}{suffix}"
            path.write_text(content, encoding="utf-8")
            parsed = None
            err = None
            try:
                parsed = parse_file_rich(path)
                ok = len(parsed.text or "") >= min_chars
                if expect_title and parsed.title:
                    ok = ok and str(expect_title).lower() in parsed.title.lower()
                elif expect_title and not parsed.title:
                    ok = False
            except Exception as exc:  # noqa: BLE001
                ok = False
                err = str(exc)
            result.total += 1
            if ok:
                result.passed += 1
            result.cases.append(
                {
                    "id": case.get("id"),
                    "suffix": suffix,
                    "supported": suffix in supported_suffixes(),
                    "chars": len(getattr(parsed, "text", "") or ""),
                    "title": getattr(parsed, "title", None),
                    "ok": ok,
                    "error": err,
                }
            )
    return result
