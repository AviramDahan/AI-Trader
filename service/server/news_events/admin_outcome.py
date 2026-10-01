"""Private final-outcome notification, in the existing analysis transaction.

No IO, model calls, trading writes, or public outbox. Unique event/version key
survives restart; original outcome time is retained by the Admin dispatcher.
"""
from datetime import datetime, timezone
from admin_messages import timestamped

STAGES={'source_analysis','quality_review','editorial_repair','repair_review',
        'schema_repair:source_analysis','schema_repair:quality_review'}
REASONS={'invalid_json','schema_validation_failed','invalid_response_structure',
         'ai_object_required','completion_failed','ai_output_truncated'}
CHECKS={'faithful','fluent_hebrew','no_unsupported_claims','numbers_grounded',
        'terminology_grounded','hebrew_present','valid_duplicate_reference'}


def message(status,error,calls):
    failed=[r for r in calls if r.get('success') is False]
    schema_fixed=any(r.get('stage','').startswith('schema_repair:') and r.get('success') for r in calls)
    if status=='interrupted_unknown':
        result='העיבוד נקטע; התוצאה אינה ידועה ונדרשת בדיקה. אין הרצה חוזרת אוטומטית.'
    elif status=='done':
        result='התאוששות: כשל הפורמט תוקן; הניתוח ובקרת האיכות הושלמו.\nאין בכך אישור פרסום — עדיין חלים כללי הניתוב והרלוונטיות.'
    elif str(error or '').startswith('news_quality_rejected:'):
        checks=[v for v in error.split(':',1)[1].split(',') if v in CHECKS]
        result=('תיקון הפורמט הצליח, אך הידיעה נדחתה בבקרת האיכות.' if schema_fixed else 'הידיעה נדחתה בבקרת האיכות.')
        result+='\nבדיקות שלא עברו: '+(', '.join(checks) or 'quality_validation')+'\nהידיעה לא פורסמה; אין ניסיון אוטומטי נוסף לגרסה זו.'
    else:
        result='כשל סופי: העיבוד לא הושלם לאחר הניסיונות המותרים.\nהידיעה לא פורסמה; אין ניסיון אוטומטי נוסף לגרסה זו.'
    if failed:
        last=failed[-1]
        stage=last.get('stage') if last.get('stage') in STAGES else 'unknown_stage'
        reason=last.get('failure_reason') if last.get('failure_reason') in REASONS else 'request_failed'
        result+='\nשלב הכשל: '+stage+'\nסיבה: '+reason
        from retry_policy import STRUCTURE_DETAILS
        if last.get('structure_detail') in STRUCTURE_DETAILS:
            result+='\nאבחון מבנה: '+last['structure_detail']
        from retry_policy import safe_json_diagnostic
        diagnostic=safe_json_diagnostic(last.get('json_diagnostic'))
        if diagnostic:
            result+='\nאבחון JSON: '+diagnostic['code']
            result+='\n'+', '.join(f'{key}={diagnostic[key]}' for key in ('line','column','position','output_chars') if key in diagnostic)
    return 'AI-Trader Admin\nתוצאת עיבוד חדשות\n'+result+'\nניטור הפוזיציות ו־TP/SL ממשיכים בנפרד.'


def persist(c,event_id,version,status,error,calls,at=None):
    if status!='interrupted_unknown' and not any(r.get('final_alert_owner') and r.get('success') is False for r in calls):
        return False # Normal successful calls/ordinary filtering are not alarms.
    stamp=(at or datetime.now(timezone.utc)).isoformat()
    body=message(status,error,calls)+'\nאירוע: '+event_id[:12]
    c.execute("""INSERT INTO admin_alerts(dedupe_key,message,status,attempts,next_at,created_at)
        VALUES(?,?,'pending',0,0,?) ON CONFLICT(dedupe_key) DO NOTHING""",
        ('canonical_ai_outcome:'+event_id+':'+version,timestamped(body,stamp),stamp))
    return True
