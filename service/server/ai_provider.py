"""Shared cloud transport. No local fallback, no database transaction over IO."""
import json
import os
import time

import jsonschema
import requests


def request_options():
    """Provider capability configuration, not a trading decision setting."""
    options = {}
    temperature = os.getenv('OPENROUTER_TEMPERATURE', '0').strip()
    if temperature:
        options['temperature'] = float(temperature)
    effort = os.getenv('OPENROUTER_REASONING_EFFORT', '').strip()
    if effort:
        if effort not in {'none','minimal','low','medium','high'}:
            raise ValueError('invalid_openrouter_reasoning_effort')
        options['reasoning'] = {'enabled': False} if effort == 'none' else {'effort': effort}
    return options


def json_completion(system, payload, *, predict=1000, schema=None, task="news"):
    model = (os.getenv("OPENROUTER_" + task.upper() + "_MODEL") or
             os.getenv("OPENROUTER_NEWS_MODEL") or os.getenv("OPENROUTER_MODEL"))
    key = os.getenv("OPENROUTER_API_KEY")
    if not model or not key:
        raise ValueError("openrouter_configuration_missing")
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=True)}]
    response_format = ({"type": "json_schema", "json_schema": {
        "name": "ai_trader_" + task, "strict": True, "schema": schema}}
        if schema else {"type": "json_object"})
    for attempt in range(2):
        try:
            response = requests.post("https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": "Bearer " + key},
                timeout=(10, min(180, max(10, int(os.getenv("AI_TIMEOUT_SECONDS", "120"))))),
                json={"model": model, "messages": messages, **request_options(),
                      "max_tokens": predict, "response_format": response_format,
                      "provider": {"require_parameters": True}})
            response.raise_for_status()
            body = response.json()
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("ai_output_truncated")
            value = json.loads(choice["message"]["content"])
            if schema:
                jsonschema.validate(value, schema)
            elif not isinstance(value, dict):
                raise ValueError("ai_object_required")
            return value
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if attempt or not (isinstance(exc, (requests.Timeout, requests.ConnectionError)) or status in {408,429,500,502,503,504}):
                raise ValueError("openrouter_transport_failed") from None
        except (ValueError, KeyError, IndexError, jsonschema.ValidationError):
            if attempt:
                raise ValueError("openrouter_schema_failed") from None
            messages.append({"role": "user", "content": "Return valid JSON matching the required schema; do not invent missing source facts."})
        time.sleep(.25)
