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
import jsonschema

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


def validate_schema(value, schema=None):
    properties=(schema or SCHEMA)['properties']
    if not isinstance(value, dict) or set(value) != set(properties):
        raise SchemaFailure("final_schema_fields")
    for key, rule in properties.items():
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
            provider=excluded.provider,model=excluded.model,
            output_tokens=excluded.output_tokens,latency=excluded.latency,retry_count=excluded.retry_count,
            result=excluded.result,reject_reason=excluded.reject_reason,ai_call_saved=excluded.ai_call_saved,
            estimated_cost=excluded.estimated_cost,attempts_json=excluded.attempts_json,updated_at=excluded.updated_at""",
            (trace["id"],trace["scan_id"],trace["ticker"],trace["rank"],trace["provider"],trace["model"],
             _total(attempts,"input_tokens"),_total(attempts,"output_tokens"),
             sum(a["latency"] for a in attempts), max(0,len(attempts)-1),trace["result"],
             trace["reject_reason"],int(trace["ai_call_saved"]),_total(attempts,"estimated_cost"),
             json.dumps(attempts),datetime.now(timezone.utc).isoformat()))
        from target_evidence import persist_checks, persist_decision
        persist_checks(conn, trace)
        persist_decision(conn, trace)
        conn.commit()
    finally:
        conn.close()


def _number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value >= 0 else None


def _cloud_content(body):
    """One completed text result; never select a preferred ambiguous decision."""
    if not isinstance(body, dict):
        raise SchemaFailure('final_response_structure')
    choices = body.get('choices')
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise SchemaFailure('final_response_structure')
    choice = choices[0]
    if choice.get('finish_reason') != 'stop':
        raise SchemaFailure('final_response_incomplete')
    message = choice.get('message')
    if (not isinstance(message, dict) or message.get('refusal')
            or message.get('tool_calls') or message.get('function_call')):
        raise SchemaFailure('final_response_structure')
    content = message.get('content')
    if not isinstance(content, str) or not content.strip() or len(content.encode()) > 65536:
        raise SchemaFailure('final_schema_missing_content')
    return content


def _usage(body):
    """Keep known billing fields even when the completion envelope is invalid."""
    value = body.get('usage') if isinstance(body, dict) else None
    usage = dict(value) if isinstance(value, dict) else {}
    if not isinstance(usage.get('completion_tokens_details'), dict):
        usage['completion_tokens_details'] = {}
    return usage


def _metadata_string(value):
    """Optional provider identifiers must be bounded text, never SQL objects."""
    return value if isinstance(value, str) and value.strip() and len(value) <= 256 else None


def review(messages, validator):
    provider, model = configuration()
    if provider not in {"ollama", "openrouter"} or not model:
        raise ValueError("final_ai_configuration")
    if provider == "openrouter" and not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise ValueError("final_ai_credentials_missing")
    timeout = min(300, max(20, int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))))
    trace = TRACE.get()
    schema=getattr(validator,'response_schema',SCHEMA)
    from ai_routing import (Route, local_completion, local_usage, fallback_reason,
                            _strict, safe_local_transport_failure)
    route = Route(provider, model)
    for attempt in range(2):  # One shared budget: retry OR repair, never both.
        provider, model = route.provider, route.model
        metrics = dict(retry_count=attempt, input_tokens=None, output_tokens=None,
                       estimated_cost=None, result="error", reject_reason=None)
        metrics.update(route.provenance())
        if provider == 'ollama_relay':metrics['estimated_cost']=0
        start = time.monotonic()
        retry = False
        body=None
        value=None
        sent=False
        try:
            if provider == 'openrouter':
                from ai_budget import check, acquire_request_slot
                check()
                acquire_request_slot()
            if trace is not None:
                trace["ai_started"] = True
            if provider == 'ollama_relay':
                sent=True
                try:
                    # Keep parseable HOLD for the existing protected repair.
                    value, body = local_completion(messages, schema, 450, validate_response=False)
                except (ValueError, jsonschema.ValidationError) as exc:
                    raise SchemaFailure('local_schema_failed') from exc
                metrics.update(input_tokens=_number(body.get('prompt_eval_count')),
                               output_tokens=_number(body.get('eval_count')),estimated_cost=0)
                content = json.dumps(value, allow_nan=False)
            elif provider == "ollama":
                response = requests.post(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat",
                    timeout=timeout, json={"model":model,"stream":False,"think":False,"format":schema,
                    "options":{"temperature":0,"num_predict":450},"messages":messages})
            else:
                from ai_provider import request_options
                sent=True
                response = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=timeout,
                    headers={"Authorization":"Bearer " + os.environ["OPENROUTER_API_KEY"]},
                    json={"model":model,"messages":messages,"max_tokens":450,
                          "reasoning":{"enabled":False},
                          **request_options(),
                          "response_format":{"type":"json_schema","json_schema":{"name":"stock_final_review","strict":True,"schema":schema}},
                          "provider":{"require_parameters":True}})
            if provider != 'ollama_relay':
                response.raise_for_status()
                body = response.json()
            if provider == 'ollama_relay':
                pass
            elif provider == "ollama":
                metrics.update(input_tokens=_number(body.get("prompt_eval_count")),output_tokens=_number(body.get("eval_count")))
                content = body.get("message",{}).get("content")
            else:
                usage = _usage(body)
                metrics.update(input_tokens=_number(usage.get("prompt_tokens")),output_tokens=_number(usage.get("completion_tokens")),
                               estimated_cost=_number(usage.get("cost")))
                if isinstance(body, dict):
                    metrics["resolved_model"] = _metadata_string(body.get("model"))
                    metrics["resolved_provider"] = _metadata_string(body.get("provider"))
                content = _cloud_content(body)
            if not isinstance(content,str):
                raise SchemaFailure("final_schema_missing_content")
            try:
                value = _strict(content)
            except json.JSONDecodeError:
                raise  # Retain the existing bounded JSON syntax repair.
            except ValueError as exc:
                raise SchemaFailure('final_schema_invalid_json') from exc
            value = validate_schema(value,schema)
            # Semantic direction errors are NOT repaired into a different decision.
            result = validator(value)
            metrics["result"] = "validated"
            if trace is not None:trace.update(provider=provider,model=model)
            if provider == 'ollama_relay':metrics['ollama_version']=body.get('ollama_version')
            return result
        except (SchemaFailure, json.JSONDecodeError) as exc:
            metrics["reject_reason"] = type(exc).__name__
            detail=getattr(exc,'entry_rationale_failure',None)
            if detail is not None:metrics['entry_rationale_failure']=detail
            # A semantic/rationale defect is not permission to shop decisions.
            if provider == 'ollama_relay' and detail is None:
                route.fallback('local_schema_failed')
            retry = attempt == 0
            if not retry:
                raise
            instruction=getattr(exc,'repair_instruction',None)
            if instruction is None and hasattr(validator,'schema_repair_instruction'):
                instruction=validator.schema_repair_instruction(value)
            messages = messages + [{"role":"user","content":instruction or
                "The previous response was not valid for the required JSON schema. Return the complete schema object only. Do not change the decision to obtain acceptance; HOLD remains valid."}]
        except requests.RequestException as exc:
            status = getattr(getattr(exc,"response",None),"status_code",None)
            if provider == 'ollama_relay':
                diagnostic=safe_local_transport_failure(getattr(exc,'local_transport_failure',None))
                if diagnostic:metrics['local_transport']=diagnostic
            metrics["reject_reason"] = "http_" + str(status) if status else type(exc).__name__
            from retry_policy import defer_openrouter
            if provider=='openrouter' and exc.response is not None: defer_openrouter(exc.response)
            if provider=='openrouter' and status == 402:
                from ai_budget import payment_rejected
                payment_rejected()
            metrics["reject_reason"] = "http_" + str(status) if status else type(exc).__name__
            retry = attempt == 0 and (isinstance(exc,(requests.Timeout,requests.ConnectionError)) or status in {408,429,500,502,503,504})
            reason=fallback_reason(exc)
            if provider=='ollama_relay' and reason=='local_context_capacity':metrics['reject_reason']=reason
            route.fallback(reason)
            if not retry:
                raise
        except Exception as exc:
            metrics["reject_reason"] = type(exc).__name__
            raise
        finally:
            metrics["latency"] = time.monotonic() - start
            if provider in {'openrouter','ollama_relay'} and sent:
                from ai_operations import record
                recorded_model = ('ollama/' + model + '@' + metrics['model_digest'] if provider=='ollama_relay' else model)
                billing_body = (local_usage(body) if provider=='ollama_relay' else
                                {'id': _metadata_string(body.get('id')), 'usage': _usage(body)}
                                if isinstance(body, dict) else None)
                record('final_stock_review',recorded_model,billing_body,start,metrics['result']=='validated',
                       metrics['reject_reason'],retry=attempt>0,notify_failure=not retry)
            if trace is not None:
                trace["attempts"].append(metrics)
                trace["result"] = "reviewing" if retry else metrics["result"]
                persist(trace)
        if retry:
            time.sleep(.25)  # Runs on the scanner thread, never the price monitor.
