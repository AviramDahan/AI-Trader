# סימולציית זכאות חדשות — 28/09/2026

## החלטה: DO NOT DEPLOY

Production נשאר `d397fe3`. השינויים בענף `codex/news-eligibility-simulation` בלבד.
לא בוצעו קריאות AI, איסוף/enrichment חדש, כתיבות לנתוני production או שליחות Telegram במסגרת הסימולציה.
אין שינוי בספים, ספקים, מסחר, final review, dedupe, quality review, freshness או תקציב.

## חלון ושיטת המדידה

- חלון מבוקש: 26/09/2026 07:39:45 עד 28/09/2026 07:39:45 UTC; בישראל 10:39–10:39.
- בפועל canonical history מתחיל ב־27/09/2026 16:37:28 UTC: כ־15.04 שעות, לא 48 שעות מלאות.
- נבדקו 1,686 אירועים קיימים, פעם אחת לכל event_id, בטרנזקציית PostgreSQL read-only.
- נעשה שימוש בגרסת התוכן האחרונה שנשמרה ובזמן האיסוף שלה, לא בשעון הנוכחי לצורך גיל הידיעה.
- השתמשנו בהרכב התיק/מעקב וב־universe הנוכחיים; אין שחזור מלא של חברות בתיק בכל רגע היסטורי.
- תוצאות AI קיימות ניתנות לשימוש רק כאשר זהות החברה וסוג האירוע לא השתנו. אין המצאת ציונים.
- enrichment שלא שמור כבר אינו מבוצע. זו סימולציה דטרמיניסטית, לא backtest מלא של LLM/ספקים/תזמון.
- תהליך ההשוואה האחרון ארך 22.30 שניות, ללא עלות AI.

## Current

- backlog_blocked: 1,316.
- identity_unverified: 325.
- unsupported_or_noise: 21.
- insufficient_information: 8.
- analyzed successfully: 10.
- quality rejected: 2; completion failed: 2.
- stale_or_future: 2.
- הגיעו לניתוח: 14 אירועים, כולם חדשות שוק; 10 הושלמו.
- portfolio/watchlist: 0 הודעות; important stock: 0; market: 10 רשומות delivery.

## Proposed

שיפורים בכל המדגם, כולל היסטוריה שלא תפורסם: זהות 483, סיווג 126, evidence 37.
מחוץ ל־backlog: זהות 52, סיווג 20, evidence 2. המדדים חופפים ואינם מספר הודעות.

לאחר כל ההגנות: 15 אירועים מתאימים דטרמיניסטית, לעומת 14 שנכנסו בעבר לניתוח.
ארבעת הכשלים ההיסטוריים אינם נשלחים שוב לניתוח. התוספת היא מועמדת DELL אחת בלבד.
Neutral recovered: 0 אירועי מניות עם ניתוח קיים שניתן להוכיח שנוספו לניתוב.

התפלגות החסימות לאחר ההצעה:

- backlog: 1,316 (ללא שינוי).
- identity_unverified: 267.
- unsupported_or_noise: 45 — עלייה כי אירועים שנחסמו קודם בזיהוי מגיעים עכשיו לבדיקה הזאת.
- stale_or_future: 30 — זו בדיקת גיל במועד האיסוף, לא דחייה בגלל הזמן שחלף עד הבדיקה.
- insufficient_information: 13 — מעבר חסימות מוקדמות חושף חוסר evidence.
- ללא חסם דטרמיניסטי: 15, מתוכם 14 בעלי ניסיון ניתוח שמור ואחת ללא ציוני AI.

## תחזית והעלות

אין בסיס לתחזית 8–20 הודעות ביום. מספר הודעות המניות המוכח נשאר 0.
מועמדת אחת דורשת AI כדי להכריע ברלוונטיות/מהותיות/איכות; לכן בטווח הנצפה עשויות להתווסף 0–1 הודעות לתיק, ולא הוכחה להודעה אחת.
אין מועמדת חדשה שהושלמה לחדשות מניות חשובות.

נרמול חשבוני בלבד: 1 / 15.04 × 24 ≈ 1.60 מועמדות מניות נוספות ביום.
15 / 15.04 × 24 ≈ 23.94 כלל מועמדות ה־AI ביום, כולל חדשות שוק קיימות.
אלו אינם תחזית ליום מסחר רגיל: המדגם קצר ומרביתו סוף שבוע/לילה.
Quality job כולל בדרך כלל שתי קריאות ובמקרה תיקון עד ארבע; תוספת בקצב הזה שקולה לכ־3.2–6.4 קריאות ביום, לא קריאה אחת לכל event.
אין מספיק נתוני task/event מתאימים להבטיח עלות חודשית. סימולציה: 0 קריאות, $0.
ה־$25 cap, המודל, Auto Top-Up וה־quality review לא שונו.

## דוגמאות שנבדקו

רק הדוגמה הראשונה עוברת את כל הבדיקות המוקדמות. אין 10–20 דוגמאות חדשות שעוברות, ולכן הרשימה מפרידה בין התאוששות לבין חסימה מוצדקת/פער שנותר. לכל הדוגמאות אין relevance/materiality שמורים התומכים בפרסום חדש.

1. **DELL — Dell Technologies; Investing.** “Dell Technologies general counsel sells $2.33m in shares”. קודם unsupported_or_noise; כעת insider_transaction + עובדה כספית + חברה מזוהה. מועמדת ל־AI; טופיק אפשרי תיק/מעקב בלבד אם תעבור חשיבות ורלוונטיות. Event `97c6fc3abb7d4a5484dffe6e42e3eefe`.
2. **INTC — Intel; Yahoo.** “Intel Stock Surged Over 40% in September. History Shows What's Next.” הזהות מתאוששת; נותר noise/פרשנות ביצועים. אין ניתוב, לא להציג כידיעה מאושרת לתיק.
3. **FDX — FedEx; Yahoo + scanner Yahoo.** “Giant Pandas Ping Ping and Fu Shuang Arrive in Atlanta on the FedEx Panda Express”. זהות מתאוששת; תוכן יחסי ציבור ללא סוג אירוע נתמך. אין פרסום אוטומטי למניות חשובות.
4. **QCOM — Qualcomm; Yahoo + scanner Yahoo.** “Qualcomm Stock Has an Opportunity Investors May Be Underestimating”. זהות מתאוששת; stale בעת האיסוף. אין פרסום.
5. **SBUX — Starbucks; Yahoo + scanner Yahoo.** כותרת משולבת על סגירת 250 חנויות והלוואת 401(k). זהות מתאוששת אך stale. נמצא גם סיכון סיווג קיים: earnings test של מס אינו earnings של חברה. חסום בפועל; אין טענה שהסיווג תקין.
6. **TGT — Target; Yahoo.** “Business People: Evereve hires Target exec Alanna Baker to lead digital”. קיימת התייחסות ל־Target, אבל החברה המרכזית היא Evereve. נעצר כסוג לא נתמך. זהות חברה אינה הוכחת רלוונטיות ומהותיות למניה.
7. **AMZN — Amazon; Yahoo.** “Is Amazon Stock a Buy, Hold, or Sell Below $250?” זהות מתאוששת; דעה/שאלה כללית נשארת חסומה.
8. **COIN — Coinbase; Yahoo.** “Coinbase (COIN) vs Strategy (MSTR): Which is a Better Stock to Buy?” זהות COIN מתאוששת; השוואת השקעה כללית נשארת חסומה. אין להסיק שכל סימול נוסף אושר.
9. **LOW — Lowe's; Yahoo + scanner Yahoo.** “Lowe's Companies (LOW) Starts 20 Minute Drone Delivery Pilot”. זהות מתאוששת; classifier אינו מכסה ניסוי משלוחים. זהו false-negative אפשרי שנותר, לא דחיית חשיבות מוכחת.
10. **Medpace Holdings; Investing.** “Medpace Holdings CEO August J. Troendle sells $6.75m in stock”. סוג עסקת insider מתאושש; אין זיהוי מאומת במידע/קטלוג שסופק. אין להמציא ticker או לנתב לשוק בגלל חוסר זהות.
11. **COST — Costco; Yahoo.** “Costco Costs More Than $920 a Share. Here's Why I'd Still Buy One.” זהות מתאוששת; המלצה/דעה נשארת חסומה.
12. **Dell; Investing.** “Dell CFO David Kennedy sells $14 million in company stock”. סוג האירוע מזוהה, אך המקור הקיים אינו מספק שני signals נדרשים לזיהוי Dell המקוצר. אין פרסום; זו נקודת בדיקה של metadata, לא הצדקה לעקוף אימות זהות.
13. **KR — Kroger; Yahoo.** “Walmart, Aldi, and Kroger follow Costco's lead”. זהות מתאוששת; הכותרת אינה אומרת מה קרה בצורה מספקת. נשאר חסום.
14. **MDT — Medtronic; Yahoo.** “Pfizer vs. Medtronic: Which Healthcare Turnaround is More Convincing?” זהות מתאוששת; השוואת דעות כללית נשארת חסומה.

## Quality / safety

FAIL לאישור rollout: אין הוכחת נפח/איכות מספקת. אין להסיק שיעור false positives מהדוגמה החדשה היחידה.
נמצאו סיכוני אזכור חברה שאינה נושא הידיעה, כותרות מעורבות, gaps בסיווג, והיעדר metadata תומך. הדוגמאות המסוכנות לא פורסמו בסימולציה.
בדיקות הגנת identity, evidence, neutral thresholds, dedupe ו־restart עברו. אלו בדיקות מבודדות; אינן הוכחה לאפס כפילויות עתידיות בפרודקשן.
תוצאות: 595 בדיקות Backend עברו, ועוד 29 subtests; מתוכן 104 בדיקות ממוקדות של canonical/eligibility. לא הורצו PostgreSQL integration או build חדש במסגרת משימה זו, ולא בוצעה פריסה.
אין replay של backlog, אין שידור ציבורי ואין ניסיון AI חוזר על כשל סופי.

## הצעד הבא המומלץ

לא לפרוס כעת. לבדוק את completeness של ticker metadata במתאמים הקיימים ואת סיווג ניסויים/עדכונים עסקיים מול דוגמאות אמיתיות, בלי הוספת ספקים או הורדת ספים. לאחר שיש מדגם חדש מיום מסחר ורלוונטיות/מהותיות שנמדדו באופן מאושר, להריץ השוואה נוספת. אין הרשאה משתמעת להרצת batch AI יקר.
