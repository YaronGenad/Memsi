# Memsi Interface — Deployment Runbook

מסמך הפצה: התקנת המערכת על שרת מרכזי (172.30.1.27) והפצה למחשבי-משתמשים.

---

## ארכיטקטורה

```
                       ┌─────────────────────────────┐
                       │  Server MyBranch              │
                       │  172.30.1.27                  │
                       │  Postgres 16 on disk Y:       │
                       │  - priority_cache DB          │
                       │  Always-on                    │
                       └────────────┬────────────────┘
                                    │ port 5432
                                    │ (LAN only)
              ┌─────────────────────┼─────────────────────┐
              ↓                     ↓                     ↓
        ┌──────────┐          ┌──────────┐          ┌──────────┐
        │ User PC 1│          │ User PC 2│          │ User PC N│
        │ .exe     │          │ .exe     │          │ .exe     │
        │ .env     │          │ .env     │          │ .env     │
        └──────────┘          └──────────┘          └──────────┘
```

ה-DB יושב **רק על השרת**. מחשבי-המשתמשים מריצים את ה-`.exe` המקומי שמתחבר ל-Postgres ב-172.30.1.27.

---

## Phase 1 — הקמת השרת (חד-פעמית, ~45 דקות)

### 1.1 התקנת PostgreSQL 16 על MyBranch

1. RDP אל `172.30.1.27`.
2. הורדה: <https://www.enterprisedb.com/downloads/postgres-postgresql-downloads> → "Windows x86-64" → **PostgreSQL 16**.
3. הפעלת ה-installer:
   - **Installation Directory**: `Y:\PostgreSQL\16` (לא C: — חשוב, יש לנו רק 39GB ב-C: ו-66GB ב-Y:).
   - **Data Directory**: `Y:\PostgreSQL\16\data`.
   - **Password**: ❗ **רשום בצד את הסיסמה של user `postgres`** — תצטרך אותה אחר-כך.
   - **Port**: `5432` (ברירת-מחדל).
   - **Locale**: `Default locale`.
   - **Stack Builder**: לא דרוש, אפשר לבטל.

### 1.2 פתיחת Postgres ל-connections מהרשת הפנימית

ערוך שני קבצים ב-`Y:\PostgreSQL\16\data\`:

**`postgresql.conf`** — חפש את השורה `listen_addresses` ושנה:
```
listen_addresses = '*'
```

**`pg_hba.conf`** — הוסף בסוף הקובץ:
```
# Allow connections from internal LAN
host    all             all             172.30.0.0/16           scram-sha-256
host    all             all             127.0.0.1/32            scram-sha-256
```

הפעל מחדש את ה-service:
```powershell
Restart-Service postgresql-x64-16
```

### 1.3 כלל Firewall

```powershell
New-NetFirewallRule -DisplayName "PostgreSQL LAN" `
    -Direction Inbound -Protocol TCP -LocalPort 5432 `
    -RemoteAddress 172.30.0.0/16 -Action Allow
```

### 1.4 העברת קובץ ה-dump

מהמחשב הנוכחי שלך:
```
copy c:\tmp\db_export\priority_cache_backup.dump  \\172.30.1.27\Y$\tmp\
```
(או דרך W: drive אם נוח יותר.)

### 1.5 יצירת DB ויבוא הנתונים

ב-MyBranch, פתח PowerShell עם הרשאות administrator:
```powershell
$env:PGPASSWORD = "<הסיסמה-שרשמת-בצד>"
$pgbin = "Y:\PostgreSQL\16\bin"

# יצירת DB ריק
& "$pgbin\createdb.exe" -U postgres priority_cache

# יבוא ה-dump
& "$pgbin\pg_restore.exe" -U postgres -d priority_cache --no-owner --no-acl `
    Y:\tmp\priority_cache_backup.dump

# בדיקת תקינות
& "$pgbin\psql.exe" -U postgres -d priority_cache -c "SELECT COUNT(*) FROM logfile_full;"
```

צפי: `193035` (או מספר דומה).

---

## Phase 2 — בניית installer לעצמי (חד-פעמית, ~30 דקות)

### 2.1 התקנת PyInstaller (אם לא מותקן)

```powershell
cd c:\Users\yaron\OneDrive - Newcinema\priority\priority_interface
venv\Scripts\activate
pip install pyinstaller
```

### 2.2 בניית bundle

```powershell
pyinstaller priority_interface.spec --clean --noconfirm
```

בסוף יש לך תיקייה `dist\PriorityInterface\` עם כל הקבצים (~400-600MB).

### 2.3 יצירת `.env` להפצה

צור קובץ `dist\PriorityInterface\.env` עם:
```
PRIORITY_AUTH_HEADER=Basic <ה-token-שלך>
PRIORITY_BASE_URL=https://priority.newcinema.co.il/odata/Priority/tabula.ini/ncinema

DB_HOST=172.30.1.27
DB_PORT=5432
DB_NAME=priority_cache
DB_USER=postgres
DB_PASSWORD=<הסיסמה-של-postgres-בשרת>
```

### 2.4 התקנת Inno Setup

הורדה: <https://jrsoftware.org/isinfo.php> → "Download Inno Setup".

### 2.5 בניית ה-installer

ראה `installer.iss` (קובץ ה-Inno Setup script) — מצורף לפרויקט.
פתח אותו ב-Inno Setup → לחץ Compile (F9). בסוף מקבלים: `Output\MemsiInterface_Setup.exe`.

---

## Phase 3 — התקנה על מחשב-משתמש (פעם בכל מחשב, ~3 דקות)

1. העבר את `MemsiInterface_Setup.exe` (גודל ~400MB) למחשב היעד.
2. דאבל-קליק → לחץ "Next" 3 פעמים → "Install" → "Finish".
3. דאבל-קליק על קיצור-הדרך בדסקטופ "Memsi Interface".

זהו. בלי הגדרות. ה-`.env` כבר בתוך ה-bundle.

---

## בעיות אפשריות

### "Cannot connect to DB"
- ודא שה-firewall של MyBranch פתח לפורט 5432.
- ודא שה-Postgres רץ: `Get-Service postgresql-x64-16` במחשב MyBranch.
- ודא שאתה ברשת הפנימית (`ping 172.30.1.27`).

### "Authentication failed"
- בדוק את הסיסמה ב-`.env` של המחשב שלך. אם שינית סיסמה ב-MyBranch — עדכן את כל ה-`.env` במחשבים.

### גיבוי DB
על MyBranch, הוסף משימה ב-Task Scheduler:
```powershell
schtasks /create /TN "PriorityDBBackup" /SC DAILY /ST 02:00 `
    /TR "Y:\PostgreSQL\16\bin\pg_dump.exe -U postgres -F c -f Y:\backups\priority_$(Get-Date -Format yyyyMMdd).dump priority_cache"
```
