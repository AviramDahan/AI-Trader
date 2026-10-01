"""Opt-in, bounded, encrypted diagnostic capture. Never retries or sends alerts.

Only canonical news validation failures. No prompts, request headers, reasoning,
or entire response envelopes. age public recipient only; no decryption key.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime

ROOT = Path('/app/.runtime/news-forensics')
MAX_SAMPLES = 20
MAX_BYTES = 65536
RETENTION = 86400
ALLOWED = {'invalid_json', 'schema_validation_failed', 'invalid_response_structure',
           'ai_object_required', 'ai_output_truncated'}


def redact(text):
    for key, value in os.environ.items():
        if any(part in key.upper() for part in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY', 'API_HASH', 'CHAT_ID', 'DATABASE_URL')) and len(value) >= 4:
            for variant in (value, json.dumps(value)[1:-1]):
                text = text.replace(variant, '[REDACTED]')
    text = re.sub(r'sk-[A-Za-z0-9_-]+|\d{8,}:[A-Za-z0-9_-]+', '[REDACTED]', text)
    text = re.sub(r'''(?i)(["']?(?:api[_-]?key|password|secret|token)["']?\s*[:=]\s*["']?)[^"'\s,;}]+''', r'\1[REDACTED]', text)
    text = re.sub(r'''(?i)(authorization\s*[:=]\s*|bearer\s+)[^"'\s,;}]+''', '[REDACTED]', text)
    text = re.sub(r'https?://[^\s"<>]+', '[URL]', text)
    text = re.sub(r'[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}', '[EMAIL]', text)
    return text


@contextmanager
def locked():
    import fcntl  # Linux only; unsupported platforms fail closed at caller.
    if ROOT.is_symlink():raise ValueError('unsafe_diagnostic_directory')
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    ROOT.chmod(0o700)
    fd = os.open(ROOT/'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:os.close(fd)


def prune(now):
    for path in ROOT.glob('sample-*.age'):
        # Filenames contain no user input; never follow a symbolic link.
        if path.is_symlink():continue
        if now - path.stat().st_mtime >= RETENTION:path.unlink()


def cleanup():
    try:
        if not ROOT.exists():return
        with locked():prune(time.time())
    except Exception:pass  # Diagnostics must not affect worker availability.


def capture(body, schema, model, failure):
    try:
        from news_events.call_context import CURRENT
        context = CURRENT.get()
        if not context:return
        reason = json.loads(failure).get('reason')
        if reason not in ALLOWED:return
        until = datetime.fromisoformat(os.environ.get('NEWS_FORENSICS_UNTIL', '').replace('Z', '+00:00'))
        if until.tzinfo is None:return
        now = time.time()
        deadline = until.timestamp()
        if not 0 < deadline-now <= RETENTION:return
        recipient = Path(os.environ['NEWS_FORENSICS_RECIPIENT_FILE']).read_text().strip()
        if not re.fullmatch(r'age1[0-9a-z]{58}', recipient):return
        if not isinstance(body, dict):return
        choices = body.get('choices')
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = choice.get('message')
        content = message.get('content') if isinstance(message, dict) else None
        # Bound allocations before encoding; never retain a multi-megabyte body.
        excerpt = content[:MAX_BYTES] if isinstance(content, str) else None
        clean = redact(excerpt or '').encode('utf-8')[:48000].decode('utf-8', errors='ignore')
        data = dict(captured_at=now, stage=context.get('stage'), event_id=context.get('event_id'),
                    evidence_version=context.get('version'), model=model,
                    provider=body.get('provider') if isinstance(body.get('provider'), str) else None,
                    finish_reason=choice.get('finish_reason'), schema=schema, failure=reason,
                    response_content=clean, content_type=type(content).__name__,
                    original_chars=len(content) if isinstance(content, str) else None,
                    truncated=isinstance(content, str) and (len(content)>MAX_BYTES or len(redact(excerpt or '').encode('utf-8'))>48000),
                    redaction_applied=True)
        plaintext = redact(json.dumps(data, ensure_ascii=False)).encode('utf-8')
        if len(plaintext)>MAX_BYTES:return
        json.loads(plaintext)  # Fail closed if redaction damaged diagnostic JSON.
        with locked():
            prune(now)
            state_path=ROOT/'state.json'
            if state_path.is_symlink():return
            state=json.loads(state_path.read_text()) if state_path.exists() else {'count':0,'deadline':deadline}
            # No reset on restart, expiry, changed config or cleanup. New campaign
            # requires explicit operator action; never silently replenish quota.
            if state['count']>=MAX_SAMPLES or now>=state['deadline']:return
            state['count']+=1
            fd=os.open(state_path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd,'w') as f:json.dump(state,f);f.flush();os.fsync(f.fileno())
            encrypted=subprocess.run(['age','-r',recipient],input=plaintext,stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,timeout=2,check=True).stdout
            if not encrypted.startswith(b'age-encryption.org/v1\n') or len(encrypted)>MAX_BYTES+4096:return
            path=ROOT/f"sample-{state['count']:02d}.age"
            fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd,'wb') as f:f.write(encrypted)
    except Exception:pass
