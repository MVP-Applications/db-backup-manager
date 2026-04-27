# DB Backup Manager

A web-based database backup automation tool with a modern dashboard. Manage MySQL and MongoDB database connections, trigger backups on demand, and monitor backup history — all from a clean browser UI.

---

## Features

- Register and manage MySQL and MongoDB database connections
- Trigger individual or bulk backups from the web dashboard
- Enable / disable scheduled backups per database
- View backup history: status, file size, and timestamps
- Real-time log viewer for all backup operations
- Compressed backup output (`.sql.gz` / `.archive.gz`)
- Automatic cleanup of old backups (keeps latest per database)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, FastAPI, SQLite |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| MySQL backups | `mysqldump` + gzip |
| MongoDB backups | `mongodump` (archive + gzip) |

---

## Prerequisites

Make sure the following are installed on your system before proceeding.

### System Requirements

- Python 3.8 or higher
- `mysqldump` — for MySQL backups ([MySQL Community Server](https://dev.mysql.com/downloads/))
- `mongodump` — for MongoDB backups ([MongoDB Database Tools](https://www.mongodb.com/try/download/database-tools))

### Required Directories

The application expects these directories to exist and be writable:

```bash
sudo mkdir -p /var/backups/databases
sudo mkdir -p /opt/dbbackup
sudo mkdir -p /var/log
```

> **Windows users:** These paths are Linux-style. Either run the app inside WSL/Docker, or update `BACKUP_DIR`, `DB_PATH`, and `LOG_FILE` constants at the top of `main.py` to Windows paths (e.g. `C:/backups/databases`).

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-username/db-backup-manager.git
cd db-backup-manager
```

### 2. Create and activate a virtual environment

```bash
# Create
python -m venv venv

# Activate — Linux / macOS
source venv/bin/activate

# Activate — Windows (Command Prompt)
venv\Scripts\activate.bat

# Activate — Windows (PowerShell)
venv\Scripts\Activate.ps1
```

### 3. Install Python dependencies

```bash
pip install fastapi pydantic uvicorn
```

Or, if a `requirements.txt` is present:

```bash
pip install -r requirements.txt
```

---

## Running the Application

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

For development with auto-reload on file changes:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Then open your browser at:

```
http://localhost:8000
```

---

## Configuration

All paths are configured as constants at the top of [main.py](main.py):

| Constant | Default | Description |
|---|---|---|
| `BACKUP_DIR` | `/var/backups/databases` | Root directory for all backup files |
| `DB_PATH` | `/opt/dbbackup/registry.db` | SQLite registry file location |
| `LOG_FILE` | `/var/log/db_backup.log` | Backup operation log file |

Edit these values directly in `main.py` to match your environment.

---

## Usage

### Adding a Database

1. Open `http://localhost:8000` in your browser.
2. Click **Add Database**.
3. Fill in the connection details (host, port, username, password, database name).
4. Save — the database now appears in your registry.

### Running a Backup

- Click **Backup** next to any registered database to back it up immediately.
- Click **Backup All** to trigger backups for all enabled databases at once.

### Viewing Logs

Click the **Logs** tab to see a live view of the last 100 lines from the backup log.

---

## API Reference

The backend exposes a REST API consumed by the dashboard. You can also call it directly.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/databases` | List all registered databases |
| `POST` | `/api/databases` | Add a new database |
| `GET` | `/api/databases/{id}` | Get a single database |
| `PUT` | `/api/databases/{id}` | Update database config |
| `DELETE` | `/api/databases/{id}` | Remove a database |
| `POST` | `/api/databases/{id}/backup` | Trigger backup for one database |
| `POST` | `/api/backup/all` | Backup all enabled databases |
| `GET` | `/api/logs` | Retrieve recent log lines |

Interactive API docs are available at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc`.

---

## Backup File Format

Backups are stored under `BACKUP_DIR/{db_type}/{name}/`:

| Database | Filename Pattern | Format |
|---|---|---|
| MySQL | `{name}_{timestamp}.sql.gz` | gzip-compressed SQL dump |
| MongoDB | `{name}_{timestamp}.archive.gz` | gzip-compressed mongodump archive |

Only the most recent backup is retained per database. Older files are removed automatically after each successful run.

---

## Project Structure

```
db-backup-manager/
├── main.py          # FastAPI application, backup logic, API routes
├── static/
│   └── index.html   # Single-page web dashboard
├── registry.db      # SQLite database (auto-created on first run)
└── README.md
```

---

## Automated Backups via Cron

Use a cron job to call the **Backup All** API endpoint on a schedule so backups run without manual intervention. The app must already be running when the cron job fires.

### Linux / macOS

Open your crontab:

```bash
crontab -e
```

Add a line using the format `minute hour day month weekday command`. Examples:

```cron
# Every day at 2:00 AM
0 2 * * * curl -s -X POST http://localhost:8000/api/backup/all >> /var/log/db_backup_cron.log 2>&1

# Every 6 hours
0 */6 * * * curl -s -X POST http://localhost:8000/api/backup/all >> /var/log/db_backup_cron.log 2>&1

# Every Sunday at midnight
0 0 * * 0 curl -s -X POST http://localhost:8000/api/backup/all >> /var/log/db_backup_cron.log 2>&1
```

Verify the job was saved:

```bash
crontab -l
```

> **Tip:** If `curl` is not on the cron `PATH`, use its full path (find it with `which curl`).

### Windows (Task Scheduler)

1. Open **Task Scheduler** → **Create Basic Task**.
2. Set your trigger (daily, weekly, etc.).
3. For the action choose **Start a program**:
   - Program: `curl`
   - Arguments: `-s -X POST http://localhost:8000/api/backup/all`
4. Finish and enable the task.

Alternatively, use a one-liner in PowerShell to register a daily task:

```powershell
$action  = New-ScheduledTaskAction -Execute "curl" -Argument "-s -X POST http://localhost:8000/api/backup/all"
$trigger = New-ScheduledTaskTrigger -Daily -At "02:00"
Register-ScheduledTask -TaskName "DB Backup Manager" -Action $action -Trigger $trigger -RunLevel Highest
```

### Keeping the App Running

The cron job only works while the FastAPI server is running. To keep it alive across reboots:

**Linux (systemd)**

Create `/etc/systemd/system/db-backup-manager.service`:

```ini
[Unit]
Description=DB Backup Manager
After=network.target

[Service]
User=your_user
WorkingDirectory=/path/to/db-backup-manager
ExecStart=/path/to/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable db-backup-manager
sudo systemctl start db-backup-manager
```

**Windows**

Use the Task Scheduler trigger type **At startup** (with no stop condition) or run the app via [NSSM](https://nssm.cc/) to register it as a Windows Service.

---

## Troubleshooting

**`registry.db` permission error**
Ensure the process has write access to the directory containing `DB_PATH`.

**`mysqldump: command not found`**
Install MySQL client tools and make sure `mysqldump` is on your `PATH`.

**`mongodump: command not found`**
Install [MongoDB Database Tools](https://www.mongodb.com/try/download/database-tools) and ensure `mongodump` is on your `PATH`.

**Backup directory not writable**
Run `sudo chmod -R 775 /var/backups/databases` or update `BACKUP_DIR` to a path your user owns.

---

## License

MIT
