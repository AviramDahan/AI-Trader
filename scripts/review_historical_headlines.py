"""Reviewed source-only Hebrew replacements for quarantined historical news.

These are translations of the stored headlines, not regenerated investment
analysis. No alerts, trade changes, price predictions or inferred article facts.
Original sources and the pre-repair SQLite snapshot remain available.
"""
import argparse
import re
import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service/server'))
from database import get_db_connection, begin_write_transaction

# Editorial translations of the original titles inspected on 2026-09-25.
HEADLINES={
1097:'מעבר ל־NVIDIA: שתי מניות מרכזי נתונים לבינה מלאכותית שהכתבה מציעה לרכישה לצורך פוטנציאל עלייה נוסף',
1204:'יחידה של New Era Energy & Digital חתמה על הסכם רכישת חשמל ל־20 שנה עם חברה מסונפת ל־Vistra',
1605:'Dell הצטרפה השבוע למדד S&P 100; המחזיק החיצוני הגדול ביותר שלה המשיך למכור',
1655:'טור דעה: סיבה בשווי 2.75 מיליארד דולר לרכוש מניות Micron',
1721:'טור דעה: מדוע שווי השוק החדש של AMD, טריליון דולר, הגיוני לדעת הכותב',
1722:'מניות הטכנולוגיה עולות על רקע התלהבות מחודשת מבינה מלאכותית; מחירי הנפט ותשואות האג״ח הגבוהים ממתנים את העליות',
1723:'החוזים על Nasdaq ו־S&P 500 נעצרים לאחר עליות שיא בהובלת בינה מלאכותית; AMD, META, BABA, GME, HOOD, GRAB ו־VKTX במוקד',
1727:'האם Dell משתמשת ב־XPS Googlebook כדי להעמיק את היתרון של המערכת הטכנולוגית שלה בבינה מלאכותית?',
1728:'בחינת מניות בולטות: Dell ומניות חומרה ותשתיות ברבעון השני',
1730:'מניית צינורות שהוזנחה הפכה לשותפה במיזם משותף עם מתחרה, לפי הכותרת',
1736:'מדוע Muse הוסיפה מיליארדים לשווי השוק של Meta ולהונו של מארק צוקרברג, לפי הכתבה',
1737:'שוק המניות היום: שינוי מועט ב־Nasdaq, ב־Dow וב־S&P 500, כאשר המסחר במניות בינה מלאכותית מניע את השוק',
1738:'Jefferies העלתה את מחיר היעד ל־Meta Platforms מ־710 ל־875 דולר והותירה דירוג קנייה',
1739:'Meta Platforms עלתה ב־11.3%: האם העוצמה תימשך?',
1771:'סקירת בוקר: הנפט נחלש וההתלהבות מבינה מלאכותית מתחדשת',
1772:'Muse של Meta עקפה את ChatGPT והפכה לאפליקציית iOS המובילה; הכותב טוען שהשוק כבר מתמחר מעבר צרכני לסוכני בינה מלאכותית',
1779:'Meta משתפת פעולה עם Shopify להוספת קניות ותשלום מבוססי בינה מלאכותית ל־Muse',
1787:'מעבר ל־Meta: קרן ARKG של קתי ווד מגדילה החזקות בארבע חברות ביוטכנולוגיה',
1805:'12 מניות במדד S&P 500 הגיעו לשווי של טריליון דולר: מה עלול להשתבש?',
1839:'מדוע קתי ווד קוראת להתעלם מדאגות האינפלציה והצמיחה, בעוד העליות במניות השבבים נעצרות',
1840:'רעיונות השקעה של Zacks מתמקדים ב־AMD וב־SanDisk',
1844:'הפופולריות של Muse AI מבית Meta מזנקת: האם היא תוביל את המניה לשיאים חדשים?',
1845:'התקווה מניעה את השווקים, אך המציאות עלולה להכאיב — טור דעה',
1864:'AMD מצטרפת למועדון החברות בשווי טריליון דולר עם האצת העליות במניות שבבי הבינה המלאכותית',
1865:'Mizuho: התרחיש החיובי ל־Meta מתממש במידה גוברת',
1868:'Nvidia ו־AMD אינן יכולות לייצר שבבי בינה מלאכותית ללא החברה הנדונה; הכתבה מציגה מדוע מנייתה עשויה לעלות',
1869:'Shopify מזנקת ב־7% ו־Meta נחלשת עם הוספת Shop Pay ל־Muse; Amazon אינה מצטרפת לעליות',
1897:'הכתבה מציעה שתי מניות שירותים טכנולוגיים כדי להשתתף במגמת העלייה האחרונה',
1919:'Robinhood היא מניה שבמוקד העניין: עובדות שכדאי להכיר לפני השקעה בה',
1921:'עניין רב של משקיעים ב־CrowdStrike: מה כדאי לדעת',
1924:'עדכון ענפי: מניות הטכנולוגיה יורדות לפני פתיחת המסחר ביום שלישי',
1957:'האם מניות המחשבים והטכנולוגיה מפגרות השנה אחרי BE Semiconductor Industries?',
1958:'SoFi עולה ב־5% לאחר שאיבדה מחצית מערכה: האם המניה עשויה להכפיל את שווייה מכאן?',
1967:'AMD, Viking Therapeutics, Alibaba, GameStop, Vicor ומניות נוספות שמסבירות את תנועת השוק היום',
2023:'BlackBerry תפרסם תוצאות לרבעון השני: האם המשקיעים צריכים להחזיק או לצאת?',
2036:'האם Pediatrix יכולה לשמור על צמיחה למרות ירידה במספר המטופלים?',
2066:'מניית Fortinet מזנקת על רקע ביקוש לפלטפורמת האבטחה: מה הלאה?',
2068:'Qualcomm נחלשת כאשר Googlebook פותח מסלול חדש בשוק המחשבים האישיים',
2082:'הזמנות ציוד הרשת של HPE מצביעות על המשך צמיחה: מה הלאה?',
2083:'האם מניית CrowdStrike מתאימה לרכישה כאשר איומי בינה מלאכותית מגבירים את הביקוש?',
2084:'Google מכוונת את ChromeOS לפלח היוקרתי בעוד Apple פונה לפלח נמוך יותר',
2100:'ביטקוין ומניות הקריפטו רשמו עליות חדות: הכתבה בוחנת את הסיבות',
2101:'תחזיות הכותבים למחירי מניות Marvell, AMD ו־Broadcom בשנת 2027 — לא יעדים של הסורק',
2233:'B. Riley: פגישת טראמפ ושי וכלל ה־SEC בנוגע לטוקניזציה עשויים לשמש זרזים קצרי טווח למניות קריפטו',
2262:'Cisco צונחת ב־6% בזמן שענף הטכנולוגיה עולה; Arista ו־Ciena ללא שינוי משמעותי',
2270:'טום לי: MSTR, HOOD ו־RIOT הובילו בשבוע שעבר את העליות בקרן Granny Shots של Fundstrat',
2430:'CrowdStrike נחלשת כאשר Palo Alto הופכת את איתור חולשות האבטחה לאוטומטי',
2432:'מניות שרשמו תנועות גדולות אתמול: Xponential Fitness, Meta, Marvell Technology, Titan International ו־Cloudflare',
2559:'האם מניית Arista Networks הפכה בשקט להשקעה מסוג אחר?',
2723:'הכתבה מציגה מניות ערך לרכישה כאשר שוק המניות בשיאים חדשים',
2884:'מנכ״ל Strategy, פונג לה, חושף את הטעות שמאחורי צניחת STRC ב־25%, לפי הכותרת',
2915:'האם מניית Arista Networks הפכה בשקט להשקעה מסוג אחר?',
2921:'מניית MSTR עולה במסחר הלילי; אנליסט צופה פוטנציאל עלייה של 16.5% מהמחיר הנוכחי',
2926:'האם שולי הרווח של Dell יוכלו להדביק את העלייה במניה?',
2954:'מניית CrowdStrike עולה כאשר חששות מאבטחת בינה מלאכותית יוצרים הזדמנות לדעת הכותב',
3015:'ג׳ייסון קלקניס, מקורבו של אילון מאסק, מהמר שארבע חברות בתחום האוטונומיה יירכשו בתוך שנתיים ויכפילו את כספו',
3043:'דוח השוואתי על ניטור תרופתי: Roche, Abbott, Siemens Healthineers, Thermo Fisher ו־Bio-Rad',
3044:'דוח השוואתי על שינויים בטוקסיקולוגיה בניסויים בבעלי חיים: Charles River, Labcorp, Evotec, WuXi AppTec ו־Thermo Fisher',
3129:'שתי מניות גדולות עם נתוני יסוד יציבים ומניה נוספת שהכותבים אינם מעדיפים',
3130:'דוח עולמי על סינון בתעשיית התרופות: שינויים בייצור תרופות ביולוגיות בהשתתפות Danaher, Merck KGaA, Sartorius, 3M ו־Thermo Fisher',
3146:'Robinhood הפכה בשקט לעסק מבוסס: האם למניית HOOD נותר מקום לעלייה?',
3165:'Sandisk, Super Micro, IonQ, Six Flags ומניות נוספות שמסבירות את תנועת השוק היום',
3281:'האם מניית Robinhood מפגרת בביצועיה אחרי Nasdaq?',
3282:'האם MSTR תעלה בעקבות חשיפת החזקות חדשות של טראמפ ב־Strategy של מייקל סיילור?',
3321:'האם CrowdStrike מתאימה לרכישה כאשר אנליסטים בוול סטריט נראים אופטימיים?',
3322:'מניית HCA Healthcare זזה: מה מושך את תשומת הלב היום?',
3323:'Intel זינקה ב־30% בתוך חודש: הכתבה דנה באפשרויות הפעולה',
3333:'לא Palantir ולא Micron: שותפת Nvidia בשווי 325 מיליארד דולר שג׳ים קריימר כינה מניה שחייבים לקנות',
3334:'כאשר הכול מתומחר בפרמיה, היכן מותגי טכנולוגיה מוצאים קונים חדשים?',
3418:'מדוע HPE הייתה בין התורמות הבולטות לתוצאות של Gabelli?',
3457:'האם הגעה של Prisma AIRS להכנסה שנתית חוזרת של 100 מיליון דולר תתמוך בצמיחת אבטחת הבינה המלאכותית של PANW?',
3458:'ארבע מניות שהכתבה מציעה לרכישה מענף הפתרונות הטכנולוגיים המשגשג',
3544:'HPE או AMD: איזו מניית ערך עדיפה כעת?',
3551:'הכותב מציג את Dell כאפשרות להשקעה במומנטום',
3584:'המניות יורדות כאשר וול סטריט מצמצמת חשיפה לסיכון',
3585:'כיצד אימוץ מוגבר של Azure ו־Copilot בענפים מפוקחים עשוי להשפיע על משקיעי Microsoft?',
3603:'הכתבה דנה במסחר במניית MicroStrategy בזמן שמחירי הביטקוין שוב מזנקים',
3700:'מדוע וול סטריט מעלה כעת דירוגים לחמש מניות באופן נמרץ?',
3709:'האם תמחור Dell ביחס לתזרים המזומנים סביר לאחר העלייה במניה?',
3751:'מניית Marvell עלתה, אך האם היא אותתה מראש מתי? — כותרת פרשנות',
3752:'מדוע מניית CrowdStrike עולה היום?',
3783:'מניית Cisco נראית יקרה עד שמתחשבים בתחזית השנתית שכבר מסרה, לפי הכותב',
3784:'האם מניית SanDisk מגדילה סיכון שכבר קיים בתיק שלך?',
3822:'טראמפ המעיט בחששות לבטיחות בינה מלאכותית, אך תיק ההשקעות שלו רכש מניות אבטחת סייבר',
3823:'סוכן הבינה המלאכותית Muse של Meta מעורר חששות בנוגע למניות חברות ברוקראז׳',
3897:'האם הסתיימה מגמת העלייה במומנטום של מניות שבבי הבינה המלאכותית?',
3950:'Robinhood רשמה ירידה גדולה מזו של השוק הרחב: עובדות שכדאי להכיר',
3965:'Strategy רשמה ירידה גדולה מזו של השוק: עובדות שכדאי לשים לב אליהן',
4038:'HPE משלבת מחשוב קוונטי במחשוב עתיר ביצועים במתקני הלקוח',
4083:'עסקת MSTR של דונלד טראמפ מעוררת שאלות כאשר מניית Strategy מזנקת ב־83%',
4085:'מניית שירותים אחת עם פוטנציאל מעניין ושתי מניות שהכותבים מטילים בהן ספק',
4169:'Thermo Fisher השיקה את Gibco CHO K1 Panel; הכתבה בוחנת גם את שאלת השווי ההוגן',
4177:'תחזית הענף של Zacks מתמקדת ב־Seagate Technology, Hewlett Packard, Silicon Motion Technology ו־Infleqtion',
4194:'Biodesix מקדמת תוכניות לניטור מחלה שאריתית מזערית עם Bio-Rad ו־Thermo Fisher',
4203:'בעידן הבינה המלאכותית, המזומן עדיין חשוב — טור דעה',
4268:'Fortinet ממוצבת ליהנות מהתרחבות שוק אבטחת הסייבר ומאימוץ בינה מלאכותית, לפי הכותרת',
4274:'כיצד H World Group נהנית מהתרחבות שוק הלינה המקומי בסין?',
4275:'תחזית לשוק בידוד והפרדת תאים: מ־6.97 מיליארד דולר ב־2026 ל־13.51 מיליארד ב־2032; הדוח כולל את Thermo Fisher, Bio-Rad, Beckman Coulter ו־Sartorius',
4276:'תחזית לשוק ערכות ריאגנטים לניטור תרופתי: מ־2.87 מיליארד דולר ב־2026 ל־6.96 מיליארד ב־2032; הדוח כולל את Abbott, Roche, Danaher, Siemens Healthineers ו־Thermo Fisher',
4319:'יועץ לשעבר ל־CFPB: פעילות הספורט של Kalshi מערערת את טיעוניה נגד המדינות, לפי דיווח בלעדי',
4331:'העמדה החיובית של Dodge & Cox כלפי Thermo Fisher',
4337:'האם מומנטום חזק בפתרונות SIEM מהדור הבא עשוי להניע את התרחבות הפלטפורמה של CrowdStrike?',
4376:'CrowdStrike או Figma: איזו מניית טכנולוגיה עדיפה לרכישה ב־2026?',
4377:'חברת מחקר עצמאית הגדירה את CrowdStrike כמובילה בפלטפורמות אבטחה יזומה',
4378:'HPE או Dell: איזו מניית תשתיות בינה מלאכותית היא השקעה בטוחה יותר?',
4390:'Sandisk מצטרפת ל־S&P 100: האם זרימת כספים למדד או סיפור הבינה המלאכותית מניעים את המניה?',
4415:'האם HCA יכולה לשמור על צמיחת רווחים למרות שינוי בתמהיל השירותים?',
4440:'חמש מניות עם תשואה גבוהה על ההון שהכתבה מציעה לבחון בתקופה של תנודתיות בשוק',
4441:'ל־Palantir סיפור צמיחה שמעט חברות יכולות להשתוות אליו, לפי הכותרת',
4442:'Webull יורדת ב־6% כאשר המכירות נמשכות מעבר לכותרות על מכירת בעלי עניין; Robinhood ו־Interactive Brokers יורדות ב־2%',
4476:'מניית MSTR הפכה לאחת ההשקעות החריגות ביותר בשוק, לפי הכתבה',
4516:'האם Tenet Healthcare יכולה לשמור על צמיחה למרות ירידה במספר הניתוחים?',
4631:'Marvell מול NVIDIA: אחת ממניות הבינה המלאכותית נראית עדיפה לרכישה, לדעת הכותב',
4651:'האם מניית Strategy נראית אחרת לאחר שנחשפו חשבונות הקשורים לטראמפ?',
4752:'האם שיתוף הפעולה בין CrowdStrike ל־Snowflake עשוי ליצור מנוע צמיחה חדש בבינה מלאכותית?',
4753:'בעל עניין ב־Robinhood מכר מניות בשווי 30,184,350 דולר, לפי דיווח אחרון ל־SEC',
4754:'Strategy רכשה בשבוע שעבר 950 מטבעות ביטקוין במחיר 79,670 דולר; האם מייקל סיילור ימשיך לקנות במחיר 84,000 דולר?',
4843:'מרכזי נתונים ימשיכו לתמוך בצמיחה חזקה של Marvell, לפי הכותרת',
4916:'האם מניית Arista Networks תלויה מדי בשמירה על הביקוש?',
5203:'בלוג האנליסטים של Zacks מתמקד ב־Marvell Technology וב־NVIDIA',
5225:'ג׳ים קריימר סבור ש־Robinhood מציגה ביצועים מצוינים',
5240:'מניית היום החיובית של Zacks: HPE — טור פרשנות',
}


def sec_headline(row):
    """Describe only the filing identity; never infer contents or impact."""
    title = row['title']
    form = (re.match(r'^([A-Z0-9 /-]+?)\s+-\s+', title)
            or re.search(r'— SEC ([A-Z0-9 /-]+)', title))
    if not form:
        return None
    # Derive issuer from the original title, not the old provider parser that
    # accidentally prefixed some issuer names with the K in 8-K/11-K.
    issuer = title[form.end():] if ' - ' in title else (row.get('original_publisher') or row.get('publisher') or '')
    issuer = re.sub(r'\s*\(\d+\)\s*\((?:Filer|Issuer|Subject)\)\s*$', '', issuer)
    issuer = issuer.replace(' (SEC EDGAR filer)', '')
    return f'דיווח רגולטורי מסוג {form.group(1).strip()} — {issuer}. זמין מטא־דאטה של הדיווח בלבד; לא נקבעה השפעה על מחיר המניה.'


def main(apply=False):
    conn=get_db_connection();cur=conn.cursor()
    rows=[dict(r) for r in cur.execute('SELECT * FROM scanner_news WHERE quality_version=-2')]
    changes=[]
    for r in rows:
        text=HEADLINES.get(r['id'])
        if not text and r['provider']=='sec_edgar':
            text=sec_headline(r)
        if text:changes.append((r['id'],text))
    print('Source-only historical summaries reviewed:',len(changes),'apply:',apply)
    if apply:
        backups=sorted((ROOT/'.runtime').glob('news-quality-backup-*.db'))
        if not backups:raise RuntimeError('Original database backup required')
        # Numeric IDs are not sufficient identity across installations.
        with sqlite3.connect(f'file:{backups[0].as_posix()}?mode=ro',uri=True) as original:
            for r in rows:
                if r['id'] not in HEADLINES:continue
                previous=original.execute('SELECT title,url FROM scanner_news WHERE id=?',(r['id'],)).fetchone()
                if not previous or tuple(previous)!=(r['title'],r['url']):
                    raise RuntimeError('Historical source identity mismatch; no changes applied')
        backup_path=ROOT/'.runtime'/('headline-review-backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.db')
        with sqlite3.connect(backup_path) as backup:
            conn.backup(backup)
        begin_write_transaction(cur)
        for news_id,text in changes:
            cur.execute("""UPDATE scanner_news SET title_he=?,summary_he=?,interpretation_he=?,
                sentiment=NULL,impact=NULL,materiality=NULL,relevance=NULL,thesis_effect='unchanged',
                analysis_status='reviewed_source_only',analysis_error=NULL,quality_version=2
                WHERE id=? AND quality_version=-2""",
                (text,text,'תקציר היסטורי מתוקן לפי כותרת המקור בלבד; אין כאן ניתוח השקעה חדש או סיגנל מסחר.',news_id))
            if cur.rowcount:cur.execute("UPDATE scanner_news_jobs SET status='done',last_error=NULL WHERE news_id=?",(news_id,))
        conn.commit()
    conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    main(parser.parse_args().apply)
