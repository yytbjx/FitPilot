"""跑五轮演示对话，采集每轮 LLM 上下文（prompt）与生成（completion）token。

口径：
- 本轮上下文占用 = 该轮所有 Ollama 调用的 prompt_eval_count 之和
- 累计占用 = 五轮 prompt 之和（模型侧真实进上下文窗口的 token）
- FitPilot 默认不把完整多轮历史塞进 LLM；知识问答每轮独立拼 system+证据
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
SESSION_ID = f"ctx_measure_{int(time.time())}"
OUT = Path(__file__).resolve().parents[1] / "scripts" / "five_turn_context_report.json"

# 覆盖项目核心能力：知识 RAG / 个人数据 / 知识 / 计划预览 / 复杂联合调整
TURNS = [
    {
        "id": 1,
        "intent_expect": "knowledge_query",
        "message": "减脂期蛋白质怎么安排？",
        "note": "RAG 知识问答（会调用 Ollama）",
    },
    {
        "id": 2,
        "intent_expect": "personal_data_query",
        "message": "我的档案目标和最近一周训练、饮食记录怎么样？",
        "note": "个人数据查询（确定性汇总，通常不调 LLM）",
    },
    {
        "id": 3,
        "intent_expect": "knowledge_query",
        "message": "力量训练后补水有什么建议？可以引用指南吗？",
        "note": "RAG 知识问答（第二次，上下文不叠加历史）",
    },
    {
        "id": 4,
        "intent_expect": "plan_create",
        "message": "请根据我的减脂目标生成一份训练和饮食计划预览",
        "note": "计划生成预览（确定性引擎，通常不调 LLM）",
    },
    {
        "id": 5,
        "intent_expect": "plan_adjust",
        "message": "根据我最近两周的训练记录调整饮食和训练",
        "note": "复杂联合调整（确定性引擎 + 审批，通常不调 LLM）",
    },
]


def _req(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
        raise RuntimeError(f"{method} {path} -> {e.code}: {payload}") from e


def _parse_prompt_completion(detail: str | None) -> tuple[int, int]:
    if not detail:
        return 0, 0
    m = re.search(r"prompt=(\d+)\s+completion=(\d+)", detail)
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))


def _token_monitor() -> dict:
    # status --local is CLI; use health/ready if available, else scrape via chat path.
    # Prefer /health/ready data.token_monitor when present.
    try:
        ready = _req("GET", "/health/ready")
        data = ready.get("data") or {}
        mon = data.get("token_monitor")
        if isinstance(mon, dict):
            return mon
    except Exception:
        pass
    return {}


def _latest_trace_tokens(before_ids: set[str]) -> tuple[dict | None, int, int, list[dict]]:
    traces = _req("GET", "/agent/traces?limit=10", token=_TOKEN)
    items = (traces.get("data") or {}).get("items") or []
    for tr in items:
        tid = tr.get("id")
        if tid in before_ids:
            continue
        prompt = completion = 0
        llm_steps = []
        for step in tr.get("steps") or []:
            if step.get("name") == "ollama.chat":
                p, c = _parse_prompt_completion(step.get("detail"))
                prompt += p
                completion += c
                llm_steps.append(
                    {
                        "title": step.get("title"),
                        "detail": step.get("detail"),
                        "duration_ms": step.get("duration_ms"),
                        "prompt_tokens": p,
                        "completion_tokens": c,
                    }
                )
        return tr, prompt, completion, llm_steps
    return None, 0, 0, []


_TOKEN = ""


def main() -> None:
    global _TOKEN
    login = _req(
        "POST",
        "/auth/login",
        {"email": "demo@fitpilot.local", "password": "demo123456"},
    )
    _TOKEN = ((login.get("data") or {}).get("access_token")) or ""
    if not _TOKEN:
        raise SystemExit(f"login failed: {login}")

    # 记录起始 trace id，避免把旧 trace 算进来
    existing = _req("GET", "/agent/traces?limit=50", token=_TOKEN)
    seen_ids = {t.get("id") for t in ((existing.get("data") or {}).get("items") or [])}

    mon0 = _token_monitor()
    results = []
    cum_prompt = cum_completion = 0

    for turn in TURNS:
        print(f"\n=== Turn {turn['id']}: {turn['message']} ===", flush=True)
        t0 = time.time()
        chat = _req(
            "POST",
            "/agent/chat",
            {"message": turn["message"], "session_id": SESSION_ID},
            token=_TOKEN,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        data = chat.get("data") or {}
        tr, prompt, completion, llm_steps = _latest_trace_tokens(seen_ids)
        if tr and tr.get("id"):
            seen_ids.add(tr.get("id"))

        cum_prompt += prompt
        cum_completion += completion
        row = {
            "turn": turn["id"],
            "message": turn["message"],
            "note": turn["note"],
            "intent_expect": turn["intent_expect"],
            "final_status": data.get("final_status"),
            "requires_confirmation": data.get("requires_confirmation"),
            "reply_preview": (data.get("reply") or "")[:240],
            "citations_count": len(data.get("citations") or []),
            "elapsed_ms": elapsed_ms,
            "llm_calls": len(llm_steps),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "round_total_tokens": prompt + completion,
            "cumulative_prompt_tokens": cum_prompt,
            "cumulative_completion_tokens": cum_completion,
            "cumulative_total_tokens": cum_prompt + cum_completion,
            "trace_id": (tr or {}).get("id"),
            "llm_steps": llm_steps,
        }
        results.append(row)
        print(
            json.dumps(
                {
                    "status": row["final_status"],
                    "prompt": prompt,
                    "completion": completion,
                    "cum_prompt": cum_prompt,
                    "llm_calls": row["llm_calls"],
                    "elapsed_ms": elapsed_ms,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        # 计划类若进入审批，拒绝以不污染 demo 正式计划
        if data.get("requires_confirmation") and data.get("task_id"):
            try:
                _req(
                    "POST",
                    f"/agent/tasks/{data['task_id']}/approve",
                    {"approve": False, "comment": "context-measure dry-run reject"},
                    token=_TOKEN,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"approve-reject skipped: {exc}", flush=True)

    mon1 = _token_monitor()
    # qwen2.5 常见默认上下文；若 Ollama 未显式设 num_ctx，实测以 prompt 为准
    assumed_ctx = 32768
    report = {
        "session_id": SESSION_ID,
        "model": "qwen2.5:1.5b (rag/default)",
        "assumed_context_window": assumed_ctx,
        "measurement": {
            "definition": (
                "每轮「上下文占用」= 该轮 Ollama prompt_eval_count 之和；"
                "五轮合计 = 各轮 prompt 之和（非把历史拼进同一窗口）。"
            ),
            "architecture_note": (
                "FitPilot 知识子图每轮独立拼装 system+当前问题+检索证据；"
                "前端聊天历史不回传给模型；会话仅可选压缩摘要用于个人数据路径。"
            ),
        },
        "token_monitor_before": mon0,
        "token_monitor_after": mon1,
        "turns": results,
        "summary": {
            "turns": len(results),
            "llm_turns": sum(1 for r in results if r["prompt_tokens"] > 0),
            "total_prompt_tokens": cum_prompt,
            "total_completion_tokens": cum_completion,
            "total_tokens": cum_prompt + cum_completion,
            "peak_single_turn_prompt": max((r["prompt_tokens"] for r in results), default=0),
            "peak_prompt_pct_of_32k": round(
                100.0 * max((r["prompt_tokens"] for r in results), default=0) / assumed_ctx, 3
            ),
            "cumulative_prompt_pct_of_32k": round(100.0 * cum_prompt / assumed_ctx, 3),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===", flush=True)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2), flush=True)
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
