import hashlib
import json
import os
import subprocess
import sys
import threading
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# --- CONFIGURATION ---
ENABLE_HOT_RELOAD = False  # Set to False to disable auto-reloading
# ---------------------


class RestartHandler(FileSystemEventHandler):
    def __init__(self, script_path):
        self.script_path = script_path
        self.process = None
        self.last_restart_time = 0
        self.debounce_interval = 1.0  # 1 second debounce
        self.pending_changes = set()  # changed files pending restart
        self.restart_scheduled = False  # whether a delayed restart is scheduled
        self.start_process()

    def _compute_vue_fingerprint(self, web_path):
        """Compute a stable fingerprint of frontend source/config inputs."""
        hash_obj = hashlib.sha256()

        def _hash_file(file_path, rel_path):
            hash_obj.update(rel_path.replace("\\", "/").encode("utf-8", errors="ignore"))
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    hash_obj.update(chunk)

        # Hash source tree(s)
        for folder in ("src", "public"):
            abs_folder = os.path.join(web_path, folder)
            if not os.path.isdir(abs_folder):
                continue
            for root, dirs, files in os.walk(abs_folder):
                dirs[:] = [d for d in dirs if d not in {"node_modules", "dist", ".git", ".vite"}]
                for name in sorted(files):
                    file_path = os.path.join(root, name)
                    rel_path = os.path.relpath(file_path, web_path)
                    _hash_file(file_path, rel_path)

        # Hash root files that affect build output
        root_files = (
            "index.html",
            "vite.config.js",
            "vite.config.ts",
            "tailwind.config.js",
            "tailwind.config.ts",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            ".env",
            ".env.local",
            ".env.production",
        )
        for name in root_files:
            file_path = os.path.join(web_path, name)
            if os.path.isfile(file_path):
                _hash_file(file_path, name)

        return hash_obj.hexdigest()

    def _can_skip_vue_build(self, web_path, dist_path, stamp_path):
        if os.getenv("FORCE_VUE_BUILD", "").strip().lower() in {"1", "true", "yes"}:
            print("[HotReload] FORCE_VUE_BUILD is set, forcing Vue rebuild.")
            return False

        if not os.path.isfile(os.path.join(dist_path, "index.html")):
            return False
        if not os.path.isfile(stamp_path):
            return False

        try:
            with open(stamp_path, "r", encoding="utf-8") as f:
                stamp = json.load(f)
        except Exception:
            return False

        old_fp = stamp.get("fingerprint")
        if not old_fp:
            return False

        new_fp = self._compute_vue_fingerprint(web_path)
        if old_fp == new_fp:
            print("[HotReload] Vue source unchanged, skip frontend build.")
            return True
        return False

    def _write_vue_build_stamp(self, stamp_path, fingerprint):
        with open(stamp_path, "w", encoding="utf-8") as f:
            json.dump(
                {"fingerprint": fingerprint, "updated_at": time.time()},
                f,
                ensure_ascii=False,
                indent=2,
            )

    def build_vue(self):
        """Build Vue frontend project."""
        web_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
        dist_path = os.path.join(web_path, "dist")
        stamp_path = os.path.join(web_path, ".vue_build_fingerprint.json")

        try:
            if self._can_skip_vue_build(web_path, dist_path, stamp_path):
                return True

            print("[HotReload] Building Vue frontend...")

            # Try to find npm executable
            npm_path = None

            # Method 1: npm.cmd (Windows)
            try:
                result = subprocess.run(["where", "npm.cmd"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    npm_path = result.stdout.strip().split("\n")[0]
                    print(f"[HotReload] Found npm.cmd: {npm_path}")
            except Exception:
                pass

            # Method 2: npm
            if not npm_path:
                try:
                    result = subprocess.run(["where", "npm"], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 and result.stdout.strip():
                        npm_path = result.stdout.strip().split("\n")[0]
                        print(f"[HotReload] Found npm: {npm_path}")
                except Exception:
                    pass

            # Method 3: common paths
            if not npm_path:
                common_paths = [
                    os.path.expandvars(r"%APPDATA%\npm\npm.cmd"),
                    os.path.expandvars(r"%APPDATA%\npm\npm"),
                    r"C:\Program Files\nodejs\npm.cmd",
                    r"C:\Program Files (x86)\nodejs\npm.cmd",
                ]
                for path in common_paths:
                    if os.path.exists(path):
                        npm_path = path
                        print(f"[HotReload] Found npm in common path: {npm_path}")
                        break

            if not npm_path:
                print("[HotReload] npm not found. Please install Node.js")
                print("[HotReload] Download: https://nodejs.org/")
                return False

            result = subprocess.run(
                [npm_path, "run", "build"],
                cwd=web_path,
                timeout=120,
            )

            if result.returncode == 0:
                print("[HotReload] Vue build succeeded")
                if os.path.exists(dist_path):
                    print(f"[HotReload] Build output: {dist_path}")
                else:
                    print("[HotReload] Warning: dist directory not found after build")
                fingerprint = self._compute_vue_fingerprint(web_path)
                self._write_vue_build_stamp(stamp_path, fingerprint)
                return True

            print(f"[HotReload] Vue build failed (exit code: {result.returncode})")
            return False

        except subprocess.TimeoutExpired:
            print("[HotReload] Vue build timed out (120s)")
            return False
        except FileNotFoundError:
            print("[HotReload] npm not found. Please install Node.js")
            return False
        except Exception as e:
            print(f"[HotReload] Build error: {e}")
            return False

    def start_process(self):
        # Re-check to prevent concurrent process leftovers
        if self.process and self.process.poll() is None:
            self.stop_process_tree()

        # Build Vue first (will be skipped if unchanged)
        self.build_vue()

        print(f"[HotReload] Starting {self.script_path}...")
        self.process = subprocess.Popen([sys.executable, self.script_path])

    def on_any_event(self, event):
        # 0. Global switch
        if not ENABLE_HOT_RELOAD:
            return

        # Watch selected file types only
        valid_ext = (".py", ".qss", ".json", ".vue", ".js", ".ts")
        if not event.src_path.endswith(valid_ext):
            return

        # Ignore generated/unrelated directories
        # Ignore web changes here to prevent backend restarts from frontend edits.
        if (
            "__pycache__" in event.src_path
            or ".git" in event.src_path
            or "node_modules" in event.src_path
            or "dist" in event.src_path
            or "web" in event.src_path
        ):
            return

        current_time = time.time()
        self.pending_changes.add(os.path.basename(event.src_path))

        if self.restart_scheduled:
            return

        # debounce window: 3s since last restart
        if current_time - self.last_restart_time < 3.0:
            self.restart_scheduled = True

            def delayed_restart():
                wait_time = 3.0 - (current_time - self.last_restart_time)
                if wait_time > 0:
                    time.sleep(wait_time)
                self._do_restart()
                self.restart_scheduled = False
                self.pending_changes.clear()

            threading.Thread(target=delayed_restart, daemon=True).start()
            return

        self._do_restart()

    def _do_restart(self):
        """Perform restart operation."""
        changes = ", ".join(list(self.pending_changes)[:5])
        if len(self.pending_changes) > 5:
            changes += f" ... (+{len(self.pending_changes) - 5} more)"
        print(f"\n[HotReload] Changes detected: {changes}")

        self.last_restart_time = time.time()

        if self.process:
            self.stop_process_tree()
            time.sleep(0.5)

        self.start_process()

    def stop_process_tree(self):
        """Stop current process tree."""
        if not self.process:
            return
        try:
            pid = self.process.pid
            print(f"[HotReload] Cleaning old process (PID: {pid})...")
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                self.process.terminate()
                self.process.wait(timeout=1)
        except Exception as e:
            print(f"[HotReload] Process cleanup error: {e}")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    path = "."
    script = "main.py"

    print("[HotReload] Dev hot-reload mode started")
    print(f"[HotReload] Watching: {os.path.abspath(path)}")
    print(f"[HotReload] Target script: {script}")

    event_handler = RestartHandler(script)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[HotReload] Exiting...")
        if event_handler.process:
            event_handler.process.terminate()
        observer.stop()
    observer.join()
