use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;
use tauri::Manager;

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 8000;
const BACKEND_BASE_URL: &str = "http://127.0.0.1:8000";
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

struct PackagedBackend(Mutex<Option<Child>>);

impl Drop for PackagedBackend {
    fn drop(&mut self) {
        if let Ok(mut child_slot) = self.0.lock() {
            if let Some(child) = child_slot.as_mut() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

#[tauri::command]
fn backend_base_url() -> &'static str {
    BACKEND_BASE_URL
}

fn backend_is_ready() -> bool {
    TcpStream::connect((BACKEND_HOST, BACKEND_PORT)).is_ok()
}

fn wait_for_backend(timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if backend_is_ready() {
            return true;
        }
        thread::sleep(Duration::from_millis(200));
    }
    false
}

fn packaged_backend_path() -> Option<PathBuf> {
    let current_exe = std::env::current_exe().ok()?;
    let app_dir = current_exe.parent()?;
    let backend_name = if cfg!(windows) {
        "homework_helper.exe"
    } else {
        "homework_helper"
    };
    let backend = app_dir.join(backend_name);
    backend.exists().then_some(backend)
}

fn spawn_packaged_backend_if_needed() -> Option<Child> {
    if backend_is_ready() {
        return None;
    }

    let backend = packaged_backend_path()?;
    let mut command = Command::new(backend);
    command.arg("--run-server");

    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    match command.spawn() {
        Ok(child) => {
            let _ = wait_for_backend(Duration::from_secs(10));
            Some(child)
        }
        Err(error) => {
            eprintln!("failed to spawn packaged HomeworkHelper backend: {error}");
            None
        }
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![backend_base_url])
        .setup(|app| {
            let backend = spawn_packaged_backend_if_needed();
            app.manage(PackagedBackend(Mutex::new(backend)));

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_resizable(false);
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run HomeworkHelper Tauri shell");
}
