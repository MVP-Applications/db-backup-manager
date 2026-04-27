import os, subprocess, gzip, shutil, logging, tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3

# ── Config ────────────────────────────────────────────────
BACKUP_DIR = Path("/var/backups/databases")
DB_PATH    = Path("/opt/dbbackup/registry.db")
LOG_FILE   = Path("/var/log/db_backup.log")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dbbackup")

app = FastAPI(title="DB Backup Manager")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── SQLite setup ──────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS databases (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL UNIQUE,
                db_type         TEXT NOT NULL CHECK(db_type IN ('mysql','mongodb')),
                host            TEXT,
                port            INTEGER,
                username        TEXT,
                password        TEXT,
                database_name   TEXT,
                connection_string TEXT,
                backup_enabled  INTEGER DEFAULT 1,
                created_at      TEXT DEFAULT (datetime('now')),
                last_backup_at  TEXT,
                last_backup_size INTEGER,
                last_backup_status TEXT
            )
        """)

init_db()

# ── Pydantic models ───────────────────────────────────────
class DBEntry(BaseModel):
    name: str
    db_type: str
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    database_name: Optional[str] = None
    connection_string: Optional[str] = None
    backup_enabled: int = 1

class DBUpdate(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    database_name: Optional[str] = None
    connection_string: Optional[str] = None
    backup_enabled: Optional[int] = None

# ── Backup helpers ────────────────────────────────────────
def log_msg(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    log.info(msg)

def run_backup(db: dict) -> dict:
    name     = db["name"]
    db_type  = db["db_type"]
    date     = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    db_dir   = BACKUP_DIR / db_type / name
    db_dir.mkdir(parents=True, exist_ok=True)
    cnf_path = None

    if db_type == "mongodb":
        conn_str = db["connection_string"] or (
            f"mongodb://{db['username']}:{db['password']}@{db['host']}:{db['port']}/{db['database_name']}"
        )
        out_file = db_dir / f"{name}_{date}.archive.gz"
        cmd = ["mongodump", f"--uri={conn_str}", f"--archive={out_file}", "--gzip"]

    elif db_type == "mysql":
        out_file = db_dir / f"{name}_{date}.sql.gz"
        cnf_content = (
            f"[client]\n"
            f"host={db['host']}\n"
            f"port={db['port'] or 3306}\n"
            f"user={db['username']}\n"
            f"password={db['password'] or ''}\n"
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cnf', delete=False) as f:
            f.write(cnf_content)
            cnf_path = f.name
        os.chmod(cnf_path, 0o600)
        cmd = [
            "mysqldump",
            f"--defaults-file={cnf_path}",
            "--skip-lock-tables",
            "--no-tablespaces",
            "--quick",
            "--routines",
            "--triggers",
            db["database_name"]
        ]

    else:
        return {"status": "failed", "error": "Unknown db_type"}

    try:
        log_msg(f"START backup: {name} ({db_type})")

        if db_type == "mysql":
            with gzip.open(out_file, "wb") as gz:
                proc = subprocess.run(cmd, stdout=gz, stderr=subprocess.PIPE)
        else:
            proc = subprocess.run(cmd, stderr=subprocess.PIPE)

        if proc.returncode != 0:
            err = proc.stderr.decode()
            log_msg(f"FAILED backup: {name} — {err}")
            out_file.unlink(missing_ok=True)
            return {"status": "failed", "error": err}

        size = out_file.stat().st_size

        for old in db_dir.iterdir():
            if old != out_file:
                old.unlink(missing_ok=True)

        log_msg(f"SUCCESS backup: {name} — {size} bytes → {out_file}")
        return {"status": "success", "file": str(out_file), "size": size}

    except Exception as e:
        log_msg(f"ERROR backup: {name} — {e}")
        out_file.unlink(missing_ok=True)
        return {"status": "failed", "error": str(e)}

    finally:
        if cnf_path and os.path.exists(cnf_path):
            os.unlink(cnf_path)

def update_backup_status(db_id: int, status: str, size: Optional[int]):
    with get_conn() as c:
        c.execute("""
            UPDATE databases
            SET last_backup_at=datetime('now'), last_backup_status=?, last_backup_size=?
            WHERE id=?
        """, (status, size, db_id))

# ── API Routes ────────────────────────────────────────────

@app.get("/api/databases")
def list_databases():
    with get_conn() as c:
        rows = c.execute("SELECT * FROM databases ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/databases", status_code=201)
def add_database(entry: DBEntry):
    try:
        with get_conn() as c:
            c.execute("""
                INSERT INTO databases
                (name, db_type, host, port, username, password, database_name, connection_string, backup_enabled)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (entry.name, entry.db_type, entry.host, entry.port,
                  entry.username, entry.password, entry.database_name,
                  entry.connection_string, entry.backup_enabled))
        return {"message": "Database added"}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "A database with this name already exists")

@app.get("/api/databases/{db_id}")
def get_database(db_id: int):
    with get_conn() as c:
        row = c.execute("SELECT * FROM databases WHERE id=?", (db_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)

@app.put("/api/databases/{db_id}")
def update_database(db_id: int, data: DBUpdate):
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Nothing to update")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with get_conn() as c:
        c.execute(f"UPDATE databases SET {set_clause} WHERE id=?", (*fields.values(), db_id))
    return {"message": "Updated"}

@app.delete("/api/databases/{db_id}")
def delete_database(db_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM databases WHERE id=?", (db_id,))
    return {"message": "Deleted"}

@app.post("/api/databases/{db_id}/backup")
def trigger_backup(db_id: int):
    with get_conn() as c:
        row = c.execute("SELECT * FROM databases WHERE id=?", (db_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    result = run_backup(dict(row))
    update_backup_status(db_id, result["status"], result.get("size"))
    return result

@app.post("/api/backup/all")
def backup_all():
    with get_conn() as c:
        rows = c.execute("SELECT * FROM databases WHERE backup_enabled=1").fetchall()
    results = {}
    for row in rows:
        db = dict(row)
        result = run_backup(db)
        update_backup_status(db["id"], result["status"], result.get("size"))
        results[db["name"]] = result
    return results

@app.get("/api/logs")
def get_logs(lines: int = 100):
    if not LOG_FILE.exists():
        return {"logs": ""}
    with open(LOG_FILE) as f:
        all_lines = f.readlines()
    return {"logs": "".join(all_lines[-lines:])}

# ── Serve frontend ────────────────────────────────────────
app.mount("/static", StaticFiles(directory="/opt/dbbackup/static"), name="static")

@app.get("/")
def serve_ui():
    return FileResponse("/opt/dbbackup/static/index.html")
