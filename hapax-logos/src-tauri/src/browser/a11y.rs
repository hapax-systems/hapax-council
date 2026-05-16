//! Accessibility tree extraction via CDP.
//!
//! Extracts the full A11y tree from the active page, serializes to a flat
//! text format, and writes to shm for agents to read + compress via LLMLingua-2.

use chromiumoxide::cdp::browser_protocol::accessibility::{
    AxNode, GetFullAxTreeParams, GetFullAxTreeReturns,
};
use chromiumoxide::Page;
use tauri::{AppHandle, Manager, Runtime};

use super::commands::BrowserState;

/// Extract the full accessibility tree and write to shm.
#[tauri::command]
pub async fn browser_a11y_tree<R: Runtime>(app: AppHandle<R>) -> Result<String, String> {
    let state = app.try_state::<BrowserState>().ok_or("Browser not ready")?;
    let page = state.0.active_page().await?;
    let tree = extract_a11y_tree(&page).await?;

    // Write to shm for agents
    let path = "/dev/shm/hapax-logos/browser-a11y.txt";
    std::fs::create_dir_all("/dev/shm/hapax-logos").ok();
    std::fs::write(path, &tree).ok();

    Ok(tree)
}

/// Extract and serialize the A11y tree from a page.
async fn extract_a11y_tree(page: &Page) -> Result<String, String> {
    let params = GetFullAxTreeParams::default();
    let response: GetFullAxTreeReturns = page
        .execute(params)
        .await
        .map_err(|e| format!("A11y tree extraction failed: {e}"))?
        .result;

    let nodes = &response.nodes;
    let text = serialize_ax_nodes(nodes);
    Ok(text)
}

/// Public entry point for directive watcher.
pub fn serialize_ax_nodes_pub(nodes: &[AxNode]) -> String {
    serialize_ax_nodes(nodes)
}

/// Serialize AX nodes to flat text format for LLM consumption.
///
/// Format: `[role] name: value (children: N) {node_id}`
/// Interactive elements include their backend DOM node ID for targeting.
fn serialize_ax_nodes(nodes: &[AxNode]) -> String {
    let mut lines = Vec::with_capacity(nodes.len());

    for node in nodes {
        let role_str = node
            .role
            .as_ref()
            .and_then(|r| r.value.as_ref())
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");

        // Skip ignored/invisible nodes
        if node.ignored {
            continue;
        }
        if role_str == "none" || role_str == "Ignored" {
            continue;
        }

        let name = node
            .name
            .as_ref()
            .and_then(|n| n.value.as_ref())
            .map(|v: &serde_json::Value| v.to_string())
            .unwrap_or_default();

        let value = node
            .value
            .as_ref()
            .and_then(|v| v.value.as_ref())
            .map(|v: &serde_json::Value| v.to_string())
            .unwrap_or_default();

        let child_count = node
            .child_ids
            .as_ref()
            .map(|c: &Vec<_>| c.len())
            .unwrap_or(0);

        let node_id = &node.node_id;

        let mut line = format!("[{role_str}]");
        if !name.is_empty() {
            line.push_str(&format!(" {name}"));
        }
        if !value.is_empty() {
            line.push_str(&format!(": {value}"));
        }
        if child_count > 0 {
            line.push_str(&format!(" (children: {child_count})"));
        }

        // Include node ID for interactive elements (for click/fill targeting)
        let interactive = matches!(
            role_str,
            "button"
                | "link"
                | "textbox"
                | "searchbox"
                | "combobox"
                | "checkbox"
                | "radio"
                | "tab"
                | "menuitem"
                | "option"
                | "switch"
                | "slider"
        );
        if interactive {
            line.push_str(&format!(" {{id:{}}}", node_id.as_ref()));
        }

        lines.push(line);
    }

    lines.join("\n")
}
