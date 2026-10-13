"""Retained paper-state wording only: no execution, AI, network or DB writes."""
from datetime import datetime
from zoneinfo import ZoneInfo

from entry_rejection import reason_code

ISRAEL = ZoneInfo('Asia/Jerusalem')
ENTRY_REASONS_HE = {
    'fill_rr_below_2': 'יחס הסיכוי־סיכון במחיר הביצוע נמוך מ־2R.',
    'fill_outside_plan': 'מחיר הביצוע מחוץ לטווח הסטופ והיעד השמורים.',
    'fill_stop_distance_invalid': 'מרחק הסטופ במחיר הביצוע אינו עומד בהגנות התוכנית.',
    'fill_inside_unresolved_zone': 'מחיר הביצוע בתוך אזור מחיר לא פתור.',
    'fill_no_longer_above_completed_high': 'מחיר הביצוע אינו מעל שיא 20 הסשנים שהושלמו.',
    'fill_introduces_forward_resistance': 'נמצאה התנגדות קדמית ביחס למחיר הביצוע.',
    'fill_changes_nearest_resistance': 'מחיר הביצוע משנה את ההתנגדות הקרובה שנבדקה.',
    'order_plan_mismatch': 'תוכנית הפקודה אינה תואמת לחוזה שנשמר.',
    'order_levels_mismatch': 'רמות הפקודה אינן תואמות לרמות שנשמרו.',
    'single_policy_contract_mismatch': 'תוכנית היעד היחיד אינה תואמת לחוזה שנשמר.',
    'breakout_policy_contract_mismatch': 'תוכנית הפריצה אינה תואמת לחוזה שנשמר.',
    'unsupported_single_policy': 'חוזה היעד היחיד אינו נתמך.',
    'unsupported_breakout_policy': 'חוזה הפריצה אינו נתמך.',
}


def israel_time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            return 'לא נשמר זמן חד־משמעי'
        return stamp.astimezone(ISRAEL).strftime('%d/%m/%Y %H:%M') + ' (שעון ישראל)'
    except (TypeError, ValueError):
        return 'לא נשמר זמן תקף'


def signal_state_lines(signal):
    """State when the signal alert was created, not a current fill assertion."""
    status = signal.get('status')
    if status == 'PENDING_ENTRY':
        return ['אירוע: סיגנל חדש, ממתין לכניסה', 'זכאות סיגנל: אושר',
                'ביצוע הדמה: פקודת כניסה ממתינה', 'פוזיציה: טרם נפתחה מהסיגנל הזה',
                'אישור הסיגנל אינו ביצוע. פוזיציה תיפתח רק לאחר כניסה תקפה במחיר ובחלון המותרים.']
    if status == 'PENDING_CLOSE':
        return ['אירוע: בקשת יציאה ממתינה', 'ביצוע הדמה: היציאה טרם בוצעה',
                'אין להסיק שהפוזיציה נסגרה. ניטור הסטופ והיעד הקיימים ממשיך בנפרד.']
    if status == 'RISK_BLOCKED':
        return ['אירוע: סיגנל נשמר, ביצוע הדמה נחסם', 'זכאות סיגנל: אושר',
                'ביצוע הדמה: ההקצאה לא אושרה', 'לא נפתחה פוזיציה חדשה מהסיגנל הזה.',
                'חסימת הקצאה אינה פסילת איכות הסיגנל. סיבת ההקצאה הפרטנית אינה זמינה כאן.']
    if status == 'DUPLICATE_BLOCKED':
        return ['אירוע: סיגנל נשמר, כניסה נוספת נחסמה',
                'סיבה: בקרת כפילויות מצאה פקודה או פוזיציה קיימת.',
                'לא נפתחה פוזיציה נוספת מהסיגנל הזה.']
    if status == 'BEARISH_ONLY':
        return ['אירוע: איתות שלילי בלבד', 'אין פקודת יציאה ללונג מהסיגנל הזה.',
                'לא בוצעה מכירה או פתיחת פוזיציה בעקבות ההתראה הזאת.']
    if status == 'HOLD':
        return ['אירוע: סקירה הסתיימה בהמתנה', 'לא אושרה בקשת כניסה חדשה.']
    return ['אירוע: סיגנל מתועד', 'מצב הביצוע אינו מאומת בהודעה הזאת.',
            'אין להסיק מהסיגנל לבדו שנפתחה או נסגרה פוזיציה.']


def order_update_lines(status, action, rejection=None):
    """Only an actual stored order transition; never a hypothetical fill."""
    closing = action == 'SELL'
    not_executed = ('לא בוצעה יציאה מהפקודה הזאת; אין להסיק שהפוזיציה נסגרה.' if closing
                    else 'לא נפתחה פוזיציה חדשה מהפקודה הזאת.')
    if status == 'invalid':
        detail = ENTRY_REASONS_HE.get(reason_code(rejection),
                                     'בקרת הביצוע נכשלה; סיבה פרטנית מאומתת לא נשמרה.')
        return ['אירוע: פקודת הדמה לא עברה את בקרות הביצוע', not_executed, 'סיבה: ' + detail,
                'הסטופ והיעד לא הוזזו כדי להכשיר את הביצוע.']
    if status == 'risk_rejected':
        return ['אירוע: ביצוע הדמה נחסם בבקרות הביצוע', not_executed,
                'סיבה: בקרת הקצאה או יחס סיכוי־סיכון במחיר הביצוע לא עברה. הרשומה אינה מפרידה בין הסיבות.',
                'זו חסימת ביצוע, לא פסילת איכות הסיגנל.']
    if status == 'expired':
        return ['אירוע: פג תוקף פקודת הדמה', not_executed,
                'סיבה: חלון הביצוע הסתיים ללא ביצוע של הפקודה. אין כניסה או יציאה אוטומטית בדיעבד.']
    if status == 'recovery_uncertain':
        return ['אירוע: ביצוע הדמה חסום עד בירור',
                'חסרה הכרעה מאומתת על חלון הביצוע; אין לנחש מילוי.',
                'הפקודה נשארת חסומה. ניטור פוזיציות קיימות ממשיך בנפרד.']
    return []
