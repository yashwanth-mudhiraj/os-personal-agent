import os
import sqlite3
import time
from dataclasses import dataclass
from typing import List
from rapidfuzz import fuzz
import subprocess

# =========================
# CONFIG
# =========================

DB_PATH = "file_index.db"    # To-do Need to be updated in production
MIN_SCORE = 70

# ---- Directories to skip entirely
EXCLUDED_DIRS = {
    "node_modules",
    ".venv",
    "venv",
    ".cache",
    ".vscode",
    ".next",
    ".git",
    "__pycache__",
    "$RECYCLE.BIN",
    "System Volume Information",
    "AppData",
    "Support Files"
    "Program Files",
    "Program Files (x86)",
    "Windows"
}

# ---- Only index these extensions (None = index everything except excluded)
INCLUDED_EXTENSIONS = {
    ".txt", ".md", ".py", ".json",
    ".docx", ".pdf", ".xlsx", ".csv",
    ".pptx", ".html", ".js", ".ts"
}

# ---- Always ignore these extensions
EXCLUDED_EXTENSIONS = {
    ".dll", ".exe", ".sys", ".tmp",
    ".log", ".cache", ".bin", ".dat",
    ".iso"
}

# =========================
# DATA MODEL
# =========================

@dataclass
class FileEntry:
    id: int
    name: str
    path: str
    type: str
    extension: str


# =========================
# DATABASE INIT
# =========================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            path TEXT UNIQUE,
            type TEXT,
            extension TEXT,
            parent TEXT,
            last_modified REAL,
            size INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_name ON files(name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_path ON files(path)")

    conn.commit()
    conn.close()


# =========================
# MULTI ROOT ENTRY
# =========================

def ensure_index(roots):
    """
    roots can be string or list of strings
    Example:
        ensure_index(["C:/Users/Yash", "D:/"])
    """
    init_db()

    if isinstance(roots, str):
        roots = [roots]

    roots = [os.path.abspath(r) for r in roots]

    for root in roots:
        ensure_single_root(root)


def ensure_single_root(root_path: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    key = f"root::{root_path}"
    c.execute("SELECT value FROM meta WHERE key=?", (key,))
    row = c.fetchone()

    if not row:
        print(f"📁 First index build for {root_path}")
        full_rebuild(root_path)
        save_meta(key, "indexed")
    else:
        print(f"📂 Incrementally updating {root_path}")
        incremental_update(root_path)

    save_meta("last_index_time", str(time.time()))
    conn.close()


# =========================
# EXTENSION FILTER
# =========================

def should_index_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()

    # Excluded extensions always blocked
    if ext in EXCLUDED_EXTENSIONS:
        return False

    # If whitelist defined → only allow those
    if INCLUDED_EXTENSIONS is not None:
        return ext in INCLUDED_EXTENSIONS

    return True


# =========================
# FULL REBUILD
# =========================

def full_rebuild(root_path: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

        parent = os.path.basename(root)

        # Folders
        for d in dirs:
            path = os.path.join(root, d)
            try:
                stat = os.stat(path)
            except:
                continue

            c.execute("""
                INSERT OR IGNORE INTO files
                (name, path, type, extension, parent, last_modified, size)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                d, path, "folder", "",
                parent,
                stat.st_mtime,
                stat.st_size
            ))

        # Files
        for f in files:
            if not should_index_file(f):
                continue

            path = os.path.join(root, f)
            try:
                stat = os.stat(path)
            except:
                continue

            ext = os.path.splitext(f)[1].lower()

            c.execute("""
                INSERT OR IGNORE INTO files
                (name, path, type, extension, parent, last_modified, size)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                f, path, "file", ext,
                parent,
                stat.st_mtime,
                stat.st_size
            ))

    conn.commit()
    conn.close()


# =========================
# INCREMENTAL UPDATE
# =========================

def incremental_update(root_path: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
            "SELECT path, last_modified FROM files WHERE path LIKE ?",
            (f"{root_path}%",)
        )
    db_files = {row[0]: row[1] for row in c.fetchall()}

    current_paths = set()

    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

        parent = os.path.basename(root)

        for name in dirs + files:
            path = os.path.join(root, name)
            current_paths.add(path)

            try:
                stat = os.stat(path)
            except:
                continue

            if os.path.isfile(path):
                if not should_index_file(name):
                    continue
                ext = os.path.splitext(name)[1].lower()
                type_ = "file"
            else:
                ext = ""
                type_ = "folder"

            mtime = stat.st_mtime
            size = stat.st_size

            if path not in db_files:
                c.execute("""
                    INSERT INTO files
                    (name, path, type, extension, parent, last_modified, size)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (name, path, type_, ext, parent, mtime, size))

            elif db_files[path] != mtime:
                c.execute("""
                    UPDATE files
                    SET last_modified=?, size=?
                    WHERE path=?
                """, (mtime, size, path))

    # Remove deleted files
    deleted = set(db_files.keys()) - current_paths
    for path in deleted:
        c.execute("DELETE FROM files WHERE path=?", (path,))

    conn.commit()
    conn.close()


def normalize_filename(name: str) -> str:
    # Remove extension
    name = os.path.splitext(name)[0]

    # Replace separators with space
    name = name.replace("_", " ").replace("-", " ")

    # Normalize whitespace
    name = " ".join(name.split())

    return name.lower()

# =========================
# SEARCH
# =========================

def search_files(query: str, limit: int = 5) -> List[FileEntry]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    normalized_query = normalize_filename(query)
    tokens = normalized_query.split()
    
    # ---- Extension Intent Detection ----
    extension_keywords = {
        "pdf": ".pdf",
        "word": ".docx",
        "doc": ".docx",
        "excel": ".xlsx",
        "sheet": ".xlsx",
        "powerpoint": ".pptx",
        "presentation": ".pptx",
    }

    # SQL prefilter
    like_clauses = []
    params = []

    for token in tokens:
        like_clauses.append("(name LIKE ? OR path LIKE ?)")
        params.extend([f"%{token}%", f"%{token}%"])

    where_clause = " AND ".join(like_clauses)

    sql = f"""
        SELECT id, name, path, type, extension, last_modified
        FROM files
        WHERE {where_clause}
        LIMIT 300
    """

    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()

    matches = []
    now = time.time()

    for row in rows:
        id_, name, path, type_, ext, last_modified = row

        filename = normalize_filename(name)
        path_lower = path.lower()

        # ---- 1️⃣ Fuzzy Base Score ----
        fuzzy_score = max(
            fuzz.token_set_ratio(normalized_query, filename),
            fuzz.token_set_ratio(normalized_query, path_lower)
        )

        # ---- 2️⃣ Exact Match Boost ----
        exact_boost = 0
        if normalized_query == filename:
            exact_boost = 40
        elif normalized_query in filename:
            exact_boost = 20

        # ---- 3️⃣ Filename Priority Boost ----
        name_vs_path_boost = 15 if normalized_query in filename else 0

        # ---- 4️⃣ Recency Boost ----
        recency_boost = 0
        age_days = (now - last_modified) / 86400
        if age_days < 1:
            recency_boost = 20
        elif age_days < 7:
            recency_boost = 10
        elif age_days < 30:
            recency_boost = 5

        # ---- 5️⃣ Extension Intent Boost ----
        extension_boost = 0
        for keyword, extension in extension_keywords.items():
            if keyword in normalized_query and ext == extension:
                extension_boost = 25

        # ---- 6️⃣ Folder Context Boost ----
        folder_boost = 0
        query_tokens = normalized_query.split()
        for token in query_tokens:
            if token in path_lower:
                folder_boost += 5

        # ---- 7️⃣ Depth Penalty (prefer shallow paths) ----
        depth_penalty = path_lower.count("\\") * 0.5

        # ---- FINAL SCORE ----
        final_score = (
            fuzzy_score
            + exact_boost
            + name_vs_path_boost
            + recency_boost
            + extension_boost
            + folder_boost
            - depth_penalty
        )

        if final_score >= MIN_SCORE:
            matches.append((final_score, row))

    matches.sort(key=lambda x: x[0], reverse=True)

    return [
        FileEntry(id=row[0], name=row[1], path=row[2], type=row[3], extension=row[4])
        for _, row in matches[:limit]
    ]


# =========================
# OPEN
# =========================

def open_entry(entry: FileEntry):
    try:
        if entry.type == "folder":
            subprocess.Popen(f'explorer "{entry.path}"')
        else:
            os.startfile(entry.path)
        return True
    except Exception as e:
        print(f"❌ Failed to open {entry.path}: {e}")
        return False


# =========================
# META SAVE
# =========================

def save_meta(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# -----------------------
# Unified entry point (assistant can call this)
# -----------------------

def handle_file_action(action: str, type: str, target: str) -> bool:
    action = action.lower().strip()
    target = target.strip()

    matches = search_files(target)

    if not matches:
        print("❌ No matching file or folder found.")
        return False

    # ------------------------
    # OPEN FILE
    # ------------------------
    if action == "open" and type == "file":
        files = [m for m in matches if m.type == "file"]

        if not files:
            print("❌ No file found.")
            return None

        if len(files) == 1:
            open_entry(files[0])
            return None

        return files  # RETURN instead of storing

    # ------------------------
    # OPEN FOLDER
    # ------------------------
    if action == "open" and type == "folder":
        folders = [m for m in matches if m.type == "folder"]

        if not folders:
            print("❌ No folder found.")
            return None

        if len(folders) == 1:
            open_entry(folders[0])
            return None

        return folders

    # ------------------------
    # LIST FOLDER
    # ------------------------
    if action == "list" and type == "folder":
        folders = [m for m in matches if m.type == "folder"]

        if not folders:
            print("❌ No folder found.")
            return None

        folder = folders[0]

        items = os.listdir(folder.path)
        print(f"📂 Contents of {folder.name}:")
        for item in items[:30]:
            print(" -", item)

        return None

    return False
