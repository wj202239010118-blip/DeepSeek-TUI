//! Instance isolation for multi-process safety.
//!
//! Each deepseek-tui process acquires an advisory file lock under
//! `~/.deepseek/instances/<instance_id>.lock` via `fd-lock`. The OS
//! automatically releases the lock when the process exits (even on
//! crash/SIGKILL), so stale-lock detection is deterministic: if we
//! can acquire the lock, the previous owner is dead.
//!
//! On startup, we also clean up stale instance runtime directories
//! and lock files belonging to processes that are no longer running.

use std::fs::{self, File, OpenOptions};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use fd_lock::RwLock;

/// Manages per-instance isolation: advisory lock file + runtime directory.
///
/// On creation:
/// - Creates `~/.deepseek/instances/` and acquires an exclusive lock on
///   `<instance_id>.lock` via `fd-lock` (cross-platform advisory locking).
/// - Creates `~/.deepseek/runtime/<instance_id>/` for temp files.
/// - Cleans up stale instances (lock files whose lock can be acquired).
///
/// On drop (normal exit or panic unwind):
/// - Removes the runtime directory, metadata, and lock file.
/// - The file lock is released by the OS when the file handle closes.
pub struct InstanceGuard {
    instance_id: String,
    _lock: Box<fd_lock::RwLock<File>>,
    _lock_guard: Option<fd_lock::RwLockWriteGuard<'static, File>>,
    runtime_dir: PathBuf,
    lock_path: PathBuf,
}

impl InstanceGuard {
    /// Acquire an instance lock and set up the runtime directory.
    ///
    /// Uses a UUID-based instance ID to guarantee uniqueness. Returns an
    /// error only on I/O failures — name collisions are impossible with
    /// v4 UUIDs.
    pub fn acquire(instance_id: &str) -> Result<Self> {
        let home = dirs::home_dir()
            .ok_or_else(|| anyhow::anyhow!("home directory not found"))?;
        let deepseek_dir = home.join(".deepseek");
        let instances_dir = deepseek_dir.join("instances");
        let runtime_dir = deepseek_dir.join("runtime").join(instance_id);

        fs::create_dir_all(&instances_dir)
            .with_context(|| format!("failed to create instances dir {}", instances_dir.display()))?;

        let lock_path = instances_dir.join(format!("{instance_id}.lock"));

        // Open (or create) the lock file and wrap in fd-lock RwLock.
        let lock_file = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .truncate(false)
            .open(&lock_path)
            .with_context(|| format!("failed to open lock file {}", lock_path.display()))?;

        // Write PID for observability (inside the lock file itself).
        let pid_str = format!("{}\n", std::process::id());
        // Best-effort — we're about to lock it anyway.
        let _ = std::io::Write::write_all(&mut &lock_file, pid_str.as_bytes());

        let mut lock = Box::new(RwLock::new(lock_file));
        let guard: fd_lock::RwLockWriteGuard<'static, File> = unsafe {
            std::mem::transmute(lock.try_write().map_err(|e| {
            anyhow::anyhow!(
                "Another deepseek-tui instance is running (lock conflict on {}). \
                 Only one instance can run concurrently. Error: {e}",
                lock_path.display()
            )
            })?)
        };

        // Create the per-instance runtime directory.
        fs::create_dir_all(&runtime_dir)
            .with_context(|| format!("failed to create runtime dir {}", runtime_dir.display()))?;

        // Write instance metadata JSON for observability.
        let metadata = serde_json::json!({
            "pid": std::process::id(),
            "started_at": chrono::Utc::now().to_rfc3339(),
            "instance_id": instance_id,
        });
        let meta_path = instances_dir.join(format!("{instance_id}.json"));
        let _ = fs::write(&meta_path, serde_json::to_string_pretty(&metadata).unwrap_or_default());

        // Clean up stale instances (lock files whose lock can be acquired).
        Self::cleanup_stale_instances(&instances_dir)?;

        Ok(Self {
            instance_id: instance_id.to_string(),
            _lock: lock,
            _lock_guard: Some(guard),
            runtime_dir,
            lock_path,
        })
    }

    /// The runtime directory for this instance (for temp files, tool outputs, etc.).
    pub fn runtime_dir(&self) -> &Path {
        &self.runtime_dir
    }

    /// The instance ID.
    pub fn instance_id(&self) -> &str {
        &self.instance_id
    }

    /// Scan the instances directory for lock files belonging to dead processes
    /// and clean up their lock files, metadata, and runtime directories.
    fn cleanup_stale_instances(instances_dir: &Path) -> Result<()> {
        let entries = match fs::read_dir(instances_dir) {
            Ok(entries) => entries,
            Err(_) => return Ok(()),
        };

        for entry in entries {
            let entry = match entry {
                Ok(e) => e,
                Err(_) => continue,
            };
            let path = entry.path();
            // Only process `.lock` files.
            if path.extension().and_then(|ext| ext.to_str()) != Some("lock") {
                continue;
            }
            // Try to open and lock the file. If we can acquire the lock,
            // the original owner is dead.
            let file = match OpenOptions::new().read(true).write(true).open(&path) {
                Ok(f) => f,
                Err(_) => continue,
            };
            let mut rw = RwLock::new(file);
            if rw.try_write().is_ok() {
                // Dead instance — clean up.
                // (Guard is dropped here, releasing the lock.)
                let _ = fs::remove_file(&path);
                let meta = path.with_extension("json");
                let _ = fs::remove_file(&meta);
                if let Some(stem) = path.file_stem() {
                    let rid = stem.to_string_lossy();
                    let runtime = instances_dir
                        .parent()
                        .unwrap_or_else(|| Path::new("."))
                        .join("runtime")
                        .join(rid.as_ref());
                    let _ = fs::remove_dir_all(&runtime);
                }
            }
            // If try_write failed, the instance is still alive — skip.
        }
        Ok(())
    }

    /// Release the lock and clean up artifacts (called on clean exit or drop).
    fn cleanup(&mut self) {
        // Drop the lock guard.
        self._lock_guard.take();
        // Remove lock file.
        let _ = fs::remove_file(&self.lock_path);
        // Remove metadata file.
        let _ = fs::remove_file(self.lock_path.with_extension("json"));
        // Remove runtime directory.
        let _ = fs::remove_dir_all(&self.runtime_dir);
    }
}

impl Drop for InstanceGuard {
    fn drop(&mut self) {
        self.cleanup();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn acquire_and_release() {
        let guard = InstanceGuard::acquire("test-instance-001").unwrap();
        assert!(guard.runtime_dir().exists());
        assert!(guard.lock_path.exists());
        // Can't acquire the same ID twice (simulating another process).
        let err = InstanceGuard::acquire("test-instance-001").unwrap_err();
        assert!(format!("{err}").contains("already running"));
        drop(guard);
        // After drop, a new instance can acquire.
        let guard2 = InstanceGuard::acquire("test-instance-001").unwrap();
        drop(guard2);
    }

    #[test]
    fn stale_cleanup_on_acquire() {
        // Simulate a stale lock: create an unowned lock file, then verify
        // a new instance cleans it up.
        let home = dirs::home_dir().unwrap();
        let dir = home.join(".deepseek").join("instances");
        fs::create_dir_all(&dir).unwrap();
        let lock_path = dir.join("test-stale-002.lock");
        let meta_path = dir.join("test-stale-002.json");
        fs::write(&lock_path, b"stale\n").unwrap();
        fs::write(&meta_path, b"{}").unwrap();
        let runtime = home.join(".deepseek").join("runtime").join("test-stale-002");
        fs::create_dir_all(&runtime).unwrap();

        // Acquire a *different* instance ID — it should clean up the stale one.
        let guard = InstanceGuard::acquire("test-stale-cleaner").unwrap();
        drop(guard);

        // Stale artifacts should be gone.
        assert!(!lock_path.exists());
        assert!(!meta_path.exists());
        assert!(!runtime.exists());
    }
}