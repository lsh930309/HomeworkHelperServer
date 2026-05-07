use tauri::Manager;

#[tauri::command]
fn backend_base_url() -> &'static str {
    "http://127.0.0.1:8000"
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![backend_base_url])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_resizable(false);
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run HomeworkHelper Tauri shell");
}
