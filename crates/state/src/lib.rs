use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;
use std::thread;

use anyhow::{Context, Result};
use chrono::Utc;
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ThreadStatus {
    Running,
    Idle,
    Completed,
    Failed,
    Paused,
    Archived,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SessionSource {
    Interactive,
    Resume,
    Fork,
    Api,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreadMetadata {
    pub id: String,
    pub rollout_path: Option<PathBuf>,
    pub preview: String,
    pub ephemeral: bool,
    pub model_provider: String,
    pub created_at: i64,
    pub updated_at: i64,
    pub status: ThreadStatus,
    pub path: Option<PathBuf>,
    pub cwd: PathBuf,
    pub cli_version: String,
    pub source: SessionSource,
    pub name: Option<String>,
    pub sandbox_policy: Option<String>,
    pub approval_mode: Option<String>,
    pub archived: bool,
    pub archived_at: Option<i64>,
    pub git_sha: Option<String>,
    pub git_branch: Option<String>,
    pub git_origin_url: Option<String>,
    pub memory_mode: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DynamicToolRecord {
    pub position: i64,
    pub name: String,
    pub description: Option<String>,
    pub input_schema: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MessageRecord {
    pub id: i64,
    pub thread_id: String,
    pub role: String,
    pub content: String,
    pub item: Option<Value>,
    pub created_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointRecord {
    pub thread_id: String,
    pub checkpoint_id: String,
    pub state: Value,
    pub created_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum JobStateStatus {
    Queued,
    Running,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobStateRecord {
    pub id: String,
    pub name: String,
    pub status: JobStateStatus,
    pub progress: Option<u8>,
    pub detail: Option<String>,
    pub created_at: i64,
    pub updated_at: i64,
}

#[derive(Debug, Clone)]
pub struct ThreadListFilters {
    pub include_archived: bool,
    pub limit: Option<usize>,
}

impl Default for ThreadListFilters {
    fn default() -> Self {
        Self {
            include_archived: false,
            limit: Some(50),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SessionIndexEntry {
    thread_id: String,
    thread_name: Option<String>,
    updated_at: i64,
    rollout_path: Option<PathBuf>,
}

const MAX_BUSY_RETRIES: u32 = 5;
const BUSY_RETRY_BASE_MS: u64 = 50;
const BUSY_RETRY_MAX_MS: u64 = 500;

#[derive(Debug, Clone)]
pub struct StateStore {
    db_path: PathBuf,
}

impl StateStore {
    /// Open (or create) the state database.
    ///
    /// Enables WAL journal mode for safe multi-process concurrent access.
    pub fn open(path: Option<PathBuf>) -> Result<Self> {
        let db_path = path.unwrap_or_else(default_state_db_path);
        if let Some(parent) = db_path.parent() {
            fs::create_dir_all(parent).with_context(|| {
                format!("failed to create state directory {}", parent.display())
            })?;
        }
        let store = Self { db_path };
        store.init_schema()?;
        store.apply_pragmas()?;
        Ok(store)
    }

    pub fn db_path(&self) -> &Path {
        &self.db_path
    }

    fn conn(&self) -> Result<Connection> {
        let conn = Connection::open(&self.db_path)
            .with_context(|| format!("failed to open state db {}", self.db_path.display()))?;
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA synchronous=NORMAL;
             PRAGMA busy_timeout=5000;
             PRAGMA foreign_keys=ON;
             PRAGMA wal_autocheckpoint=1000;",
        )
        .with_context(|| "failed to set WAL pragmas")?;
        Ok(conn)
    }

    fn apply_pragmas(&self) -> Result<()> {
        let conn = Connection::open(&self.db_path)
            .with_context(|| format!("failed to open state db for pragmas {}", self.db_path.display()))?;
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA synchronous=NORMAL;
             PRAGMA busy_timeout=5000;
             PRAGMA foreign_keys=ON;
             PRAGMA wal_autocheckpoint=1000;",
        )
        .with_context(|| "failed to set WAL pragmas")?;
        Ok(())
    }

    fn with_busy_retry<T, F>(&self, mut f: F) -> Result<T>
    where
        F: FnMut() -> Result<T>,
    {
        let mut attempts = 0u32;
        loop {
            match f() {
                Ok(value) => return Ok(value),
                Err(err) => {
                    let msg = format!("{err}");
                    let is_busy = msg.contains("database is locked");
                    if !is_busy || attempts >= MAX_BUSY_RETRIES {
                        return Err(err);
                    }
                    attempts += 1;
                    let base = (BUSY_RETRY_BASE_MS * 2u64.pow(attempts - 1)).min(BUSY_RETRY_MAX_MS);
                    let jitter = (Utc::now().timestamp_nanos_opt().unwrap_or(0) as u64) % (base / 2 + 1);
                    thread::sleep(Duration::from_millis(base + jitter));
                }
            }
        }
    }

    fn init_schema(&self) -> Result<()> {
        let conn = self.conn()?;
        conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT,
                preview TEXT NOT NULL,
                ephemeral INTEGER NOT NULL,
                model_provider TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                status TEXT NOT NULL,
                path TEXT,
                cwd TEXT NOT NULL,
                cli_version TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT,
                sandbox_policy TEXT,
                approval_mode TEXT,
                archived INTEGER NOT NULL DEFAULT 0,
                archived_at INTEGER,
                git_sha TEXT,
                git_branch TEXT,
                git_origin_url TEXT,
                memory_mode TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_threads_updated_at ON threads(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_threads_archived_at ON threads(archived_at DESC);
            CREATE INDEX IF NOT EXISTS idx_threads_archived_updated ON threads(archived, updated_at DESC);

            CREATE TABLE IF NOT EXISTS thread_dynamic_tools (
                thread_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                input_schema TEXT NOT NULL,
                PRIMARY KEY (thread_id, position),
                FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                item_json TEXT,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_thread_created_at ON messages(thread_id, created_at ASC);

            CREATE TABLE IF NOT EXISTS checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY(thread_id, checkpoint_id),
                FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_created_at ON checkpoints(thread_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER,
                detail TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at DESC);

            CREATE TABLE IF NOT EXISTS session_index (
                thread_id TEXT PRIMARY KEY,
                thread_name TEXT,
                updated_at INTEGER NOT NULL,
                rollout_path TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_session_index_updated_at ON session_index(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_session_index_name ON session_index(thread_name);
            "#,
        )
        .context("failed to initialize thread schema")?;

        self.migrate_session_index_jsonl()?;
        Ok(())
    }

    fn migrate_session_index_jsonl(&self) -> Result<()> {
        let jsonl = self.db_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join("session_index.jsonl");
        if !jsonl.exists() {
            return Ok(());
        }
        let conn = self.conn()?;
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM session_index", [], |row| row.get(0))
            .unwrap_or(0);
        if count > 0 {
            return Ok(());
        }
        let content = match fs::read_to_string(&jsonl) {
            Ok(c) => c,
            Err(_) => return Ok(()),
        };
        let mut inserted = 0usize;
        for line in content.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            if let Ok(entry) = serde_json::from_str::<SessionIndexEntry>(line) {
                let _ = conn.execute(
                    "INSERT OR REPLACE INTO session_index (thread_id, thread_name, updated_at, rollout_path) VALUES (?1, ?2, ?3, ?4)",
                    params![
                        entry.thread_id,
                        entry.thread_name,
                        entry.updated_at,
                        entry.rollout_path.map(|p| p.display().to_string()),
                    ],
                );
                inserted += 1;
            }
        }
        if inserted > 0 {
            let _ = fs::rename(&jsonl, jsonl.with_extension("jsonl.bak"));
        }
        Ok(())
    }

    pub fn upsert_thread(&self, thread: &ThreadMetadata) -> Result<()> {
        let conn = self.conn()?;
        conn.execute(
            r#"
            INSERT INTO threads (
                id, rollout_path, preview, ephemeral, model_provider, created_at, updated_at, status, path, cwd,
                cli_version, source, title, sandbox_policy, approval_mode, archived, archived_at,
                git_sha, git_branch, git_origin_url, memory_mode
            ) VALUES (
                ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10,
                ?11, ?12, ?13, ?14, ?15, ?16, ?17,
                ?18, ?19, ?20, ?21
            ) ON CONFLICT(id) DO UPDATE SET
                rollout_path = excluded.rollout_path,
                preview = excluded.preview,
                ephemeral = excluded.ephemeral,
                model_provider = excluded.model_provider,
                updated_at = excluded.updated_at,
                status = excluded.status,
                path = excluded.path,
                cwd = excluded.cwd,
                cli_version = excluded.cli_version,
                source = excluded.source,
                title = excluded.title,
                sandbox_policy = excluded.sandbox_policy,
                approval_mode = excluded.approval_mode,
                archived = excluded.archived,
                archived_at = excluded.archived_at,
                git_sha = excluded.git_sha,
                git_branch = excluded.git_branch,
                git_origin_url = excluded.git_origin_url,
                memory_mode = excluded.memory_mode
            "#,
            params![
                thread.id,
                thread.rollout_path.as_ref().map(|p| p.display().to_string()),
                thread.preview,
                thread.ephemeral,
                thread.model_provider,
                thread.created_at,
                thread.updated_at,
                thread_status_to_str(&thread.status),
                thread.path.as_ref().map(|p| p.display().to_string()),
                thread.cwd.display().to_string(),
                thread.cli_version,
                session_source_to_str(&thread.source),
                thread.name,
                thread.sandbox_policy,
                thread.approval_mode,
                thread.archived,
                thread.archived_at,
                thread.git_sha,
                thread.git_branch,
                thread.git_origin_url,
                thread.memory_mode,
            ],
        )
        .context("failed to upsert thread")?;
        Ok(())
    }

    pub fn list_threads(&self, filters: &ThreadListFilters) -> Result<Vec<ThreadMetadata>> {
        let conn = self.conn()?;
        let query = if filters.include_archived {
            "SELECT * FROM threads ORDER BY updated_at DESC".to_string()
        } else {
            "SELECT * FROM threads WHERE archived = 0 ORDER BY updated_at DESC".to_string()
        };
        let query = if let Some(limit) = filters.limit {
            format!("{query} LIMIT {limit}")
        } else {
            query
        };
        let mut stmt = conn.prepare(&query)?;
        let rows = stmt.query_map([], |row| row_to_thread(row))?;
        let mut threads = Vec::new();
        for row in rows {
            threads.push(row?);
        }
        Ok(threads)
    }

    pub fn get_thread(&self, thread_id: &str) -> Result<Option<ThreadMetadata>> {
        let conn = self.conn()?;
        conn.query_row(
            "SELECT * FROM threads WHERE id = ?1",
            params![thread_id],
            |row| row_to_thread(row),
        )
        .optional()
        .context("failed to get thread")
    }

    pub fn delete_thread(&self, thread_id: &str) -> Result<()> {
        let conn = self.conn()?;
        conn.execute("DELETE FROM threads WHERE id = ?1", params![thread_id])?;
        conn.execute("DELETE FROM session_index WHERE thread_id = ?1", params![thread_id])?;
        Ok(())
    }

    pub fn archive_thread(&self, thread_id: &str) -> Result<()> {
        let conn = self.conn()?;
        let now = Utc::now().timestamp();
        conn.execute(
            "UPDATE threads SET archived = 1, archived_at = ?1, updated_at = ?1 WHERE id = ?2",
            params![now, thread_id],
        )?;
        Ok(())
    }

    pub fn unarchive_thread(&self, thread_id: &str) -> Result<()> {
        let conn = self.conn()?;
        let now = Utc::now().timestamp();
        conn.execute(
            "UPDATE threads SET archived = 0, archived_at = NULL, updated_at = ?1 WHERE id = ?2",
            params![now, thread_id],
        )?;
        Ok(())
    }

    pub fn upsert_dynamic_tool(&self, thread_id: &str, tool: &DynamicToolRecord) -> Result<()> {
        let conn = self.conn()?;
        conn.execute(
            "INSERT OR REPLACE INTO thread_dynamic_tools (thread_id, position, name, description, input_schema) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                thread_id,
                tool.position,
                tool.name,
                tool.description,
                tool.input_schema.to_string(),
            ],
        )?;
        Ok(())
    }

    pub fn list_dynamic_tools(&self, thread_id: &str) -> Result<Vec<DynamicToolRecord>> {
        let conn = self.conn()?;
        let mut stmt = conn.prepare(
            "SELECT position, name, description, input_schema FROM thread_dynamic_tools WHERE thread_id = ?1 ORDER BY position",
        )?;
        let rows = stmt.query_map(params![thread_id], |row| {
            let input_schema: String = row.get(3)?;
            Ok(DynamicToolRecord {
                position: row.get(0)?,
                name: row.get(1)?,
                description: row.get(2)?,
                input_schema: serde_json::from_str(&input_schema).unwrap_or_default(),
            })
        })?;
        let mut tools = Vec::new();
        for row in rows {
            tools.push(row?);
        }
        Ok(tools)
    }

    pub fn insert_message(&self, msg: &MessageRecord) -> Result<i64> {
        let conn = self.conn()?;
        conn.execute(
            "INSERT INTO messages (thread_id, role, content, item_json, created_at) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                msg.thread_id,
                msg.role,
                msg.content,
                msg.item.as_ref().map(|v| v.to_string()),
                msg.created_at,
            ],
        )?;
        Ok(conn.last_insert_rowid())
    }

    pub fn list_messages(&self, thread_id: &str) -> Result<Vec<MessageRecord>> {
        let conn = self.conn()?;
        let mut stmt = conn.prepare(
            "SELECT id, thread_id, role, content, item_json, created_at FROM messages WHERE thread_id = ?1 ORDER BY created_at ASC",
        )?;
        let rows = stmt.query_map(params![thread_id], |row| {
            let item_json: Option<String> = row.get(4)?;
            Ok(MessageRecord {
                id: row.get(0)?,
                thread_id: row.get(1)?,
                role: row.get(2)?,
                content: row.get(3)?,
                item: item_json.and_then(|s| serde_json::from_str(&s).ok()),
                created_at: row.get(5)?,
            })
        })?;
        let mut msgs = Vec::new();
        for row in rows {
            msgs.push(row?);
        }
        Ok(msgs)
    }

    pub fn save_checkpoint(&self, record: &CheckpointRecord) -> Result<()> {
        let conn = self.conn()?;
        conn.execute(
            "INSERT OR REPLACE INTO checkpoints (thread_id, checkpoint_id, state_json, created_at) VALUES (?1, ?2, ?3, ?4)",
            params![
                record.thread_id,
                record.checkpoint_id,
                record.state.to_string(),
                record.created_at,
            ],
        )?;
        Ok(())
    }

    pub fn load_checkpoint(&self, thread_id: &str) -> Result<Option<CheckpointRecord>> {
        let conn = self.conn()?;
        conn.query_row(
            "SELECT thread_id, checkpoint_id, state_json, created_at FROM checkpoints WHERE thread_id = ?1 ORDER BY created_at DESC LIMIT 1",
            params![thread_id],
            |row| {
                let state_str: String = row.get(2)?;
                Ok(CheckpointRecord {
                    thread_id: row.get(0)?,
                    checkpoint_id: row.get(1)?,
                    state: serde_json::from_str(&state_str).unwrap_or_default(),
                    created_at: row.get(3)?,
                })
            },
        )
        .optional()
        .context("failed to load checkpoint")
    }

    pub fn upsert_job(&self, job: &JobStateRecord) -> Result<()> {
        let conn = self.conn()?;
        conn.execute(
            "INSERT OR REPLACE INTO jobs (id, name, status, progress, detail, created_at, updated_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                job.id,
                job.name,
                job_state_status_to_str(&job.status),
                job.progress,
                job.detail,
                job.created_at,
                job.updated_at,
            ],
        )?;
        Ok(())
    }

    pub fn list_jobs(&self) -> Result<Vec<JobStateRecord>> {
        let conn = self.conn()?;
        let mut stmt = conn.prepare(
            "SELECT id, name, status, progress, detail, created_at, updated_at FROM jobs ORDER BY updated_at DESC",
        )?;
        let rows = stmt.query_map([], |row| {
            let status_raw: String = row.get(2)?;
            Ok(JobStateRecord {
                id: row.get(0)?,
                name: row.get(1)?,
                status: job_state_status_from_str(&status_raw),
                progress: row.get(3)?,
                detail: row.get(4)?,
                created_at: row.get(5)?,
                updated_at: row.get(6)?,
            })
        })?;
        let mut jobs = Vec::new();
        for row in rows {
            jobs.push(row?);
        }
        Ok(jobs)
    }

    // ── Session Index (SQLite-based) ───────────────────────────────────────

    pub fn append_thread_name(
        &self,
        thread_id: &str,
        thread_name: Option<String>,
        updated_at: i64,
        rollout_path: Option<PathBuf>,
    ) -> Result<()> {
        self.with_busy_retry(|| {
            let conn = self.conn()?;
            conn.execute(
                "INSERT OR REPLACE INTO session_index (thread_id, thread_name, updated_at, rollout_path) VALUES (?1, ?2, ?3, ?4)",
                params![
                    thread_id,
                    thread_name,
                    updated_at,
                    rollout_path.clone().map(|p| p.display().to_string()),
                ],
            )?;
            Ok(())
        })
    }

    pub fn find_thread_name_by_id(&self, thread_id: &str) -> Result<Option<String>> {
        let conn = self.conn()?;
        conn.query_row(
            "SELECT thread_name FROM session_index WHERE thread_id = ?1",
            params![thread_id],
            |row| row.get(0),
        )
        .optional()
        .context("failed to find thread name")
    }

    pub fn find_thread_names_by_ids(
        &self,
        ids: &[String],
    ) -> Result<HashMap<String, Option<String>>> {
        if ids.is_empty() {
            return Ok(HashMap::new());
        }
        let conn = self.conn()?;
        let placeholders: Vec<String> = ids.iter().enumerate().map(|(i, _)| format!("?{}", i + 1)).collect();
        let query = format!(
            "SELECT thread_id, thread_name FROM session_index WHERE thread_id IN ({})",
            placeholders.join(",")
        );
        let mut stmt = conn.prepare(&query)?;
        let params: Vec<&dyn rusqlite::types::ToSql> = ids.iter().map(|id| id as &dyn rusqlite::types::ToSql).collect();
        let rows = stmt.query_map(params.as_slice(), |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?))
        })?;
        let mut out: HashMap<String, Option<String>> = ids.iter().map(|id| (id.clone(), None)).collect();
        for row in rows {
            let (id, name): (String, Option<String>) = row?;
            out.insert(id, name);
        }
        Ok(out)
    }

    pub fn find_thread_path_by_name_str(&self, name: &str) -> Result<Option<PathBuf>> {
        let conn = self.conn()?;
        let result: Option<String> = conn
            .query_row(
                "SELECT rollout_path FROM session_index WHERE thread_name = ?1 COLLATE NOCASE ORDER BY updated_at DESC LIMIT 1",
                params![name],
                |row| row.get(0),
            )
            .optional()
            .context("failed to find thread path by name")?;
        Ok(result.map(PathBuf::from))
    }

    fn session_index_map(&self) -> Result<HashMap<String, SessionIndexEntry>> {
        let conn = self.conn()?;
        let mut stmt = conn.prepare(
            "SELECT thread_id, thread_name, updated_at, rollout_path FROM session_index",
        )?;
        let rows = stmt.query_map([], |row| {
            let rollout: Option<String> = row.get(3)?;
            Ok(SessionIndexEntry {
                thread_id: row.get(0)?,
                thread_name: row.get(1)?,
                updated_at: row.get(2)?,
                rollout_path: rollout.map(PathBuf::from),
            })
        })?;
        let mut map = HashMap::new();
        for row in rows {
            let entry = row?;
            map.insert(entry.thread_id.clone(), entry);
        }
        Ok(map)
    }
}

fn default_state_db_path() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".deepseek")
        .join("state.db")
}

fn bool_to_i64(value: bool) -> i64 {
    if value { 1 } else { 0 }
}

fn i64_to_bool(value: i64) -> bool {
    value != 0
}

fn thread_status_to_str(status: &ThreadStatus) -> &'static str {
    match status {
        ThreadStatus::Running => "running",
        ThreadStatus::Idle => "idle",
        ThreadStatus::Completed => "completed",
        ThreadStatus::Failed => "failed",
        ThreadStatus::Paused => "paused",
        ThreadStatus::Archived => "archived",
    }
}

fn thread_status_from_str(value: &str) -> ThreadStatus {
    match value {
        "running" => ThreadStatus::Running,
        "idle" => ThreadStatus::Idle,
        "completed" => ThreadStatus::Completed,
        "failed" => ThreadStatus::Failed,
        "paused" => ThreadStatus::Paused,
        "archived" => ThreadStatus::Archived,
        _ => ThreadStatus::Idle,
    }
}

fn session_source_to_str(source: &SessionSource) -> &'static str {
    match source {
        SessionSource::Interactive => "interactive",
        SessionSource::Resume => "resume",
        SessionSource::Fork => "fork",
        SessionSource::Api => "api",
        SessionSource::Unknown => "unknown",
    }
}

fn session_source_from_str(value: &str) -> SessionSource {
    match value {
        "interactive" => SessionSource::Interactive,
        "resume" => SessionSource::Resume,
        "fork" => SessionSource::Fork,
        "api" => SessionSource::Api,
        _ => SessionSource::Unknown,
    }
}

fn job_state_status_to_str(status: &JobStateStatus) -> &'static str {
    match status {
        JobStateStatus::Queued => "queued",
        JobStateStatus::Running => "running",
        JobStateStatus::Completed => "completed",
        JobStateStatus::Failed => "failed",
        JobStateStatus::Cancelled => "cancelled",
    }
}

fn job_state_status_from_str(value: &str) -> JobStateStatus {
    match value {
        "queued" => JobStateStatus::Queued,
        "running" => JobStateStatus::Running,
        "completed" => JobStateStatus::Completed,
        "failed" => JobStateStatus::Failed,
        "cancelled" => JobStateStatus::Cancelled,
        _ => JobStateStatus::Queued,
    }
}

fn path_to_opt_string(path: Option<&Path>) -> Option<String> {
    path.map(|p| p.display().to_string())
}

fn row_to_thread(row: &rusqlite::Row<'_>) -> rusqlite::Result<ThreadMetadata> {
    let status_raw: String = row.get(7)?;
    let source_raw: String = row.get(11)?;
    let rollout_path: Option<String> = row.get(1)?;
    let path: Option<String> = row.get(8)?;
    Ok(ThreadMetadata {
        id: row.get(0)?,
        rollout_path: rollout_path.map(PathBuf::from),
        preview: row.get(2)?,
        ephemeral: i64_to_bool(row.get(3)?),
        model_provider: row.get(4)?,
        created_at: row.get(5)?,
        updated_at: row.get(6)?,
        status: thread_status_from_str(&status_raw),
        path: path.map(PathBuf::from),
        cwd: PathBuf::from(row.get::<_, String>(9)?),
        cli_version: row.get(10)?,
        source: session_source_from_str(&source_raw),
        name: row.get(12)?,
        sandbox_policy: row.get(13)?,
        approval_mode: row.get(14)?,
        archived: i64_to_bool(row.get(15)?),
        archived_at: row.get(16)?,
        git_sha: row.get(17)?,
        git_branch: row.get(18)?,
        git_origin_url: row.get(19)?,
        memory_mode: row.get(20)?,
    })
}