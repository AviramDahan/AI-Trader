"""Bounded final-review transport and private, durable per-candidate telemetry.

No trading writes; every telemetry connection is closed before network IO.
"""
import json
import math
import os
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

import requests

TRACE = ContextVar("final_review_trace", default=None)
PROPERTIES = {
    "action": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "news_sentiment": {"type": "number", "minimum": -1, "maximum": 1},
    "news_relevance": {"type": "number", "minimum": 0, "maximum": 1},
    "time_horizon": {"type": "string", "enum": ["1-5 trading days", "1-4 weeks", "1-3 months"]},
    "reason": {"type": "string"},
}
SCHEMA = {"type": "object", "properties": PROPERTIES,
          "required": list(PROPERTIES), "additionalProperties": False}


class SchemaFailure(ValueError):
    pass


def validate_schema(value):
    if not isinstance(value, dict) or set(value) != set(PROPERTIES):
        raise SchemaFailure("final_schema_fields")
    for key, rule in PROPERTIES.items():
        v = value[key]
        if rule["type"] == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not rule["minimum"] <= v <= rule["maximum"]:
                raise SchemaFailure("final_schema_number")
        elif not isinstance(v, str) or not v.strip() or ("enum" in rule and v not in rule["enum"]):
            raise SchemaFailure("final_schema_string")
    return value


def configuration():
    provider = os.getenv("STOCK_SCANNER_FINAL_AI_PROVIDER", "ollama").strip().lower()
    if os.getenv("AI_TRADER_CLOUD") == "true" and provider != "openrouter":
        raise ValueError("cloud_requires_openrouter")
    model = (os.getenv("STOCK_SCANNER_FINAL_AI_MODEL") or
             (os.getenv("OLLAMA_MODEL", "qwen3.5:9b-q4_K_M") if provider == "ollama" else ""))
    return provider, model


def new_trace(scan_id, ticker, rank):
    provider, model = configuration()
    return dict(id=uuid.uuid4().hex, scan_id=scan_id, ticker=ticker, rank=rank,
                provider=provider, model=model, attempts=[], result="pending",
                reject_reason=None, ai_call_saved=False, ai_started=False)


def _total(attempts, name):
    values = [a.get(name) for a in attempts]
    return sum(values) if values and all(v is not None for v in values) else None


def persist(trace):
    from database import get_db_connection
    attempts = trace["attempts"]
    conn = get_db_connection()
    try:
        conn.cursor().execute("""INSERT INTO scanner_final_ai_telemetry
            (review_id,scan_id,ticker,rank,provider,model,input_tokens,output_tokens,latency,
             retry_count,result,reject_reason,ai_call_saved,estimated_cost,attempts_json,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(review_id) DO UPDATE SET input_tokens=excluded.input_tokens,
            output_tokens=excluded.output_tokens,latency=excluded.latency,retry_count=excluded.retry_count,
            result=excluded.result,reject_reason=excluded.reject_reason,ai_call_saved=excluded.ai_call_saved,
            estimated_cost=excluded.estimated_cost,attempts_json=excluded.attempts_json,updated_at=excluded.updated_at""",
            (trace["id"],trace["scan_id"],trace["ticker"],trace["rank"],trace["provider"],trace["model"],
             _total(attempts,"input_tokens"),_total(attempts,"output_tokens"),
             sum(a["latency"] for a in attempts), max(0,len(attempts)-1),trace["result"],
             trace["reject_reason"],int(trace["ai_call_saved"]),_total(attempts,"estimated_cost"),
             json.dumps(attempts),datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()


def _number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value >= 0 else None


def review(messages, validator):
    provider, model = configuration()
    if provider not in {"ollama", "openrouter"} or not model:
        raise ValueError("final_ai_configuration")
    if provider == "openrouter" and not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise ValueError("final_ai_credentials_missing")
    timeout = min(300, max(20, int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))))
    trace = TRACE.get()
    for attempt in range(2):  # One shared budget: retry OR repair, never both.
        metrics = dict(retry_count=attempt, input_tokens=None, output_tokens=None,
                       estimated_cost=None, result="error", reject_reason=None)
        start = time.monotonic()
        retry = False
        try:
            if provider == 'openrouter':
                from ai_budget import check, acquire_request_slot
                check()
                acquire_request_slot()
            if trace is not None:
                trace["ai_started"] = True
            if provider == "ollama":
                response = requests.post(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat",
                    timeout=timeout, json={"model":model,"stream":False,"think":False,"format":SCHEMA,
                    "options":{"temperature":0,"num_predict":450},"messages":messages})
            else:
                from ai_provider import request_options
                response = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=timeout,
                    headers={"Authorization":"Bearer " + os.environ["OPENROUTER_API_KEY"]},
                    json={"model":model,"messages":messages,"max_tokens":450,
                          "reasoning":{"enabled":False},
                          **request_options(),
                          "response_format":{"type":"json_schema","json_schema":{"name":"stock_final_review","strict":True,"schema":SCHEMA}},
                          "provider":{"require_parameters":True}})
            response.raise_for_status()
            body = response.json()
            if provider == "ollama":
                metrics.update(input_tokens=_number(body.get("prompt_eval_count")),output_tokens=_number(body.get("eval_count")))
                content = body.get("message",{}).get("content")
            else:
                usage = body.get("usage") or {}
                metrics.update(input_tokens=_number(usage.get("prompt_tokens")),output_tokens=_number(usage.get("completion_tokens")),
                               estimated_cost=_number(usage.get("cost")))
                metrics["resolved_model"] = body.get("model")
                metrics["resolved_provider"] = body.get("provider")
                content = (body.get("choices") or [{}])[0].get("message",{}).get("content")
            if not isinstance(content,str):
                raise SchemaFailure("final_schema_missing_content")
            value = validate_schema(json.loads(content))
            # Semantic direction errors are NOT repaired into a different decision.
            result = validator(value)
            metrics["result"] = "validated"
            return result
        except (SchemaFailure, json.JSONDecodeError) as exc:
            metrics["reject_reason"] = type(exc).__name__
            retry = attempt == 0
            if not retry:
                raise
            messages = messages + [{"role":"user","content":"The previous response was not valid for the required JSON schema. Return the complete schema object only. Do not change the decision to obtain acceptance; HOLD remains valid."}]
        except requests.RequestException as exc:
            status = getattr(getattr(exc,"response",None),"status_code",None)
            metrics["reject_reason"] = "http_" + str(status) if status else type(exc).__name__
            retry = attempt == 0 and (isinstance(exc,(requests.Timeout,requests.ConnectionError)) or status in {408,429,500,502,503,504})
            if not retry:
                raise
        except Exception as exc:
            metrics["reject_reason"] = type(exc).__name__
            raise
        finally:
            metrics["latency"] = time.monotonic() - start
            if trace is not None:
                trace["attempts"].append(metrics)
                trace["result"] = "reviewing" if retry else metrics["result"]
                persist(trace)
        if retry:
            time.sleep(.25)  # Runs on the scanner thread, never the price monitor.
