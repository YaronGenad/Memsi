import requests
import pandas as pd
import calendar
from datetime import datetime
from dateutil.relativedelta import relativedelta
from domain_repository import (
    get_repair_price, is_repair_item, get_replacement_price,
    identify_luggage, list_customers,
)
from cache_manager import CacheManager
from errors import ConfigError, TransientNetworkError
from logger import logger

import os
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# load_dotenv כבר רץ ב-db_config.py בעת import.


def _auth_header() -> str:
    """טוען AUTH_HEADER lazy מהסביבה. זורק ConfigError אם חסר.
    כך ש-import של הקובץ לא קורס במכונות בלי .env מוגדר."""
    h = os.environ.get('PRIORITY_AUTH_HEADER')
    if not h:
        raise ConfigError(
            "PRIORITY_AUTH_HEADER לא מוגדר. ערוך את .env והגדר את המשתנה."
        )
    return h


_BASE_URL     = os.environ.get('PRIORITY_BASE_URL', 'https://priority.newcinema.co.il/odata/Priority/tabula.ini/ncinema')
DOCUMENTS_URL = f"{_BASE_URL}/DOCUMENTS_D"
LOGFILE_URL   = f"{_BASE_URL}/LOGFILE"

# Priority OData עלול להיות איטי תחת עומס; timeout של 30s היה קצר מדי
# וגרם ל-ReadTimeout. עכשיו 120s עם 5 ניסיונות.
ODATA_TIMEOUT = int(os.environ.get('PRIORITY_TIMEOUT', 120))

# שגיאות-רשת זמניות שמצדיקות retry. ConnectionError/Timeout מטופלים על-ידי
# requests; HTTP 5xx ועומס-שרת מטופלים על-ידי הקוד שלנו דרך TransientNetworkError.
_RETRY = retry(
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout, TransientNetworkError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    reraise=True,
)


def get_target_customers() -> list[str]:
    """מחזיר את רשימת הלקוחות הפעילים שמהם מושכים נתונים. נטען lazy מה-DB."""
    return [c['code'] for c in list_customers() if c.get('is_active', True)]


# תאימות-לאחור: השם _target_customers נשמר כ-alias
_target_customers = get_target_customers

def _fetch_odata_all(url: str, params: dict, progress=None) -> list:
    """שולף כל הדפים מ-OData endpoint עם $top/$skip pagination.
    progress: callable(str) אופציונלי לעדכוני התקדמות."""
    headers = {"Authorization": _auth_header()}
    all_records = []
    params = dict(params)
    params['$top'] = 1000
    params['$skip'] = 0

    @_RETRY
    def _page(p):
        r = requests.get(url, headers=headers, params=p, timeout=ODATA_TIMEOUT)
        if r.status_code >= 500:
            # שגיאת שרת זמנית — Priority נחנק, נסה שוב.
            logger.warning("OData %s HTTP %s (transient): %s", url, r.status_code, r.text[:300])
            raise TransientNetworkError(f"Priority HTTP {r.status_code}")
        if r.status_code != 200:
            # שגיאה ברמת-בקשה: 4xx, שלא תיפתר ע"י retry.
            logger.error("OData %s HTTP %s: %s", url, r.status_code, r.text[:300])
            raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json().get('value', [])

    while True:
        batch = _page(params)
        all_records.extend(batch)
        if progress:
            progress(f"  {url.rsplit('/', 1)[-1]}: {len(all_records):,} רשומות…")
        if len(batch) < 1000:
            break
        params['$skip'] += 1000
        logger.debug("_fetch_odata_all %s: fetched %d so far", url, len(all_records))

    return all_records


def fetch_documents(start_date, end_date, progress=None):
    customer_filter = ' or '.join([f"CUSTNAME eq '{c}'" for c in _target_customers()])
    params = {
        '$filter': f"(CURDATE ge {start_date}T00:00:00Z and CURDATE le {end_date}T23:59:59Z) and ({customer_filter})"
    }
    records = _fetch_odata_all(DOCUMENTS_URL, params, progress=progress)
    logger.info("fetch_documents %s→%s: %d records", start_date, end_date, len(records))
    return records


def fetch_logfile(start_date, end_date, progress=None):
    customer_filter = ' or '.join([f"CUSTNAME eq '{c}'" for c in _target_customers()])
    params = {
        '$filter': f"(CURDATE ge {start_date}T00:00:00Z and CURDATE le {end_date}T23:59:59Z) and ({customer_filter})"
    }
    records = _fetch_odata_all(LOGFILE_URL, params, progress=progress)
    logger.info("fetch_logfile %s→%s: %d records", start_date, end_date, len(records))
    return records

def fetch_with_cache(start_date, end_date, progress=None):
    """
    משיך נתונים עם שימוש ב-cache
    אם הנתונים קיימים ב-cache - מחזיר משם
    אחרת - מושך מ-API ושומר ב-cache
    """
    cache = CacheManager()
    
    # בדיקה אילו חודשים חסרים
    missing_docs = cache.get_missing_months(start_date, end_date, 'documents')
    missing_logs = cache.get_missing_months(start_date, end_date, 'logfile')
    
    # משיכת חודשים חסרים
    for year_month in set(missing_docs + missing_logs):
        year, month = map(int, year_month.split('-'))
        last_day = calendar.monthrange(year, month)[1]
        month_start = f"{year}-{month:02d}-01"
        month_end = f"{year}-{month:02d}-{last_day}"
        
        logger.info("fetch_with_cache: pulling %s from API", year_month)
        if progress:
            progress(f"מושך {year_month}…")

        if year_month in missing_docs:
            docs = fetch_documents(month_start, month_end, progress=progress)
            if progress:
                progress(f"שומר {len(docs)} מסמכים ל-cache…")
            cache.save_documents(docs, year_month)
            cache.update_metadata('documents', year_month, month_start, month_end, len(docs))

        if year_month in missing_logs:
            logs = fetch_logfile(month_start, month_end, progress=progress)
            if progress:
                progress(f"שומר {len(logs)} תנועות ל-cache…")
            cache.save_logfile(logs, year_month)
            cache.update_metadata('logfile', year_month, month_start, month_end, len(logs))
    
    # שליפה מ-cache
    logger.debug("fetch_with_cache: loading from cache %s → %s", start_date, end_date)
    documents = cache.get_documents(start_date, end_date)
    logfile = cache.get_logfile(start_date, end_date)
    
    cache.close()
    return documents, logfile

def combine_data(documents, logfile_records):
    # המרה ל-DataFrame
    docs_df = pd.DataFrame([{
        'תעודה': d.get('DOCNO'),
        'תאריך': d.get('CURDATE'),
        'הערה 1 לכתיבה': d.get('RETL_DETAILS1'),
        'מספר לקוח': d.get('CUSTNAME'),
        'שם לקוח': d.get('CUSTDES'),
        'שם לקוח קופה': d.get('CDES'),
        'פרטים': d.get('DETAILS'),
        'סטטוס': d.get('STATDES'),
        'לטיפול': d.get('OWNERLOGIN'),
        'סניף': d.get('BRANCHNAME')
    } for d in documents])
    
    log_df = pd.DataFrame([{
        'תעודה': l.get('LOGDOCNO'),
        'מקט': l.get('PARTNAME'),
        'תיאור מוצר': l.get('TOPARTDES'),
        'כמות': l.get('TQUANT'),
        'מחיר ליחידה': l.get('UCOST'),
        'מספר לקוח_log': l.get('CUSTNAME')
    } for l in logfile_records])
    
    # חיבור לפי תעודה
    if log_df.empty:
        return docs_df
    combined = docs_df.merge(log_df, on='תעודה', how='inner')
    
    # הוספת עמודות סוג פעולה, זיהוי מחוודה וחיוב ללקוח
    combined['זיהוי מזוודה'] = combined.apply(
        lambda row: identify_luggage(row['תיאור מוצר']), axis=1
    )
    
    # קביעת סוג פעולה וחיוב
    def calculate_operation_and_charge(row):
        if is_repair_item(row['מקט']):
            repair_price = get_repair_price(row['מספר לקוח'], row['מקט'])
            return 'תיקון', repair_price * row['כמות'] if repair_price else None
        elif row['זיהוי מזוודה']:
            replacement_price = get_replacement_price(row['מספר לקוח'], row['זיהוי מזוודה'])
            return 'החלפה', replacement_price * row['כמות'] if replacement_price else None
        return '', None
    
    combined[['סוג פעולה', 'חיוב ללקוח']] = combined.apply(
        lambda row: pd.Series(calculate_operation_and_charge(row)), axis=1
    )
    
    # הסרת עמודת עזר
    combined = combined.drop('מספר לקוח_log', axis=1)
    
    return combined
