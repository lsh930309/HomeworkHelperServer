use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;
use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WindowEvent,
};

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

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return Err("허용되지 않은 URL 형식입니다.".into());
    }

    #[cfg(windows)]
    let mut command = {
        let mut command = Command::new("rundll32.exe");
        command.args(["url.dll,FileProtocolHandler", url.as_str()]);
        command.creation_flags(CREATE_NO_WINDOW);
        command
    };

    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = Command::new("open");
        command.arg(url.as_str());
        command
    };

    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = {
        let mut command = Command::new("xdg-open");
        command.arg(url.as_str());
        command
    };

    command.spawn().map_err(|error| error.to_string())?;
    Ok(())
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

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn hide_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            show_main_window(app);
        }))
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            backend_base_url,
            open_external_url
        ])
        .setup(|app| {
            let backend = spawn_packaged_backend_if_needed();
            app.manage(PackagedBackend(Mutex::new(backend)));

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_resizable(false);
            }
            if let Some(window) = app.get_webview_window("sidebar") {
                let _ = window.set_resizable(false);
                let _ = window.set_always_on_top(true);
                let _ = window.set_decorations(false);
                let _ = window.set_skip_taskbar(true);
            }

            let show_item = MenuItemBuilder::with_id("show", "열기").build(app)?;
            let hide_item = MenuItemBuilder::with_id("hide", "숨기기").build(app)?;
            let quit_item = MenuItemBuilder::with_id("quit", "종료").build(app)?;
            let tray_menu = MenuBuilder::new(app)
                .items(&[&show_item, &hide_item, &quit_item])
                .build()?;

            let mut tray = TrayIconBuilder::with_id("main-tray")
                .tooltip("HomeworkHelper 새 GUI 미리보기")
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main_window(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            Ok(())
        })
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => show_main_window(app),
            "hide" => hide_main_window(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run HomeworkHelper Tauri shell");
}
