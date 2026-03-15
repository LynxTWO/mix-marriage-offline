use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopSmokeConfig {
    layout_standard: String,
    render_target: String,
    scene_locks_path: Option<String>,
    stems_dir: String,
    summary_path: String,
    workspace_dir: String,
}

fn non_empty_env(name: &str) -> Option<String> {
    let raw = std::env::var(name).ok()?;
    let value = raw.trim();
    if value.is_empty() {
        return None;
    }
    Some(value.to_owned())
}

#[tauri::command]
fn desktop_smoke_config() -> Option<DesktopSmokeConfig> {
    let summary_path = non_empty_env("MMO_DESKTOP_SMOKE_SUMMARY_PATH")?;
    let stems_dir = non_empty_env("MMO_DESKTOP_SMOKE_STEMS_DIR")?;
    let workspace_dir = non_empty_env("MMO_DESKTOP_SMOKE_WORKSPACE_DIR")?;
    let render_target = non_empty_env("MMO_DESKTOP_SMOKE_RENDER_TARGET")
        .unwrap_or_else(|| "TARGET.STEREO.2_0".to_owned());
    let layout_standard = non_empty_env("MMO_DESKTOP_SMOKE_LAYOUT_STANDARD")
        .unwrap_or_else(|| "SMPTE".to_owned());

    Some(DesktopSmokeConfig {
        layout_standard,
        render_target,
        scene_locks_path: non_empty_env("MMO_DESKTOP_SMOKE_SCENE_LOCKS_PATH"),
        stems_dir,
        summary_path,
        workspace_dir,
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![desktop_smoke_config])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
