use serde::Serialize;

// --- Briefing ---

#[derive(Debug, Clone, Serialize)]
pub struct BriefingData {
    pub headline: String,
    pub generated_at: String,
    pub body: String,
    pub action_items: Vec<ActionItem>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ActionItem {
    pub priority: String,
    pub action: String,
    pub reason: String,
    pub command: String,
}

#[tauri::command]
pub fn get_briefing() -> Option<BriefingData> {
    let primary = expand_home("~/.hapax/profiles/briefing.md");
    let path = if std::path::Path::new(&primary).exists() {
        primary
    } else {
        expand_home("~/projects/hapax-council/profiles/briefing.md")
    };
    let content = std::fs::read_to_string(&path).ok()?;
    parse_briefing(&content)
}

fn parse_briefing(content: &str) -> Option<BriefingData> {
    let mut headline = String::new();
    let mut generated_at = String::new();
    let mut body = String::new();
    let mut action_items = Vec::new();
    let mut in_body = false;
    let mut in_actions = false;
    let mut current_action: Option<(String, String)> = None;

    for line in content.lines() {
        // Extract generated_at from "*Generated ..." line
        if line.starts_with("*Generated") && line.contains('*') {
            let inner = line.trim_start_matches('*').trim_end_matches('*').trim();
            if let Some(at) = inner.strip_prefix("Generated") {
                generated_at = at.trim().to_string();
            }
            continue;
        }

        if line.starts_with("## Action Items") {
            in_body = false;
            in_actions = true;
            // Flush any pending action
            if let Some((pri, act)) = current_action.take() {
                action_items.push(ActionItem {
                    priority: pri,
                    action: act,
                    reason: String::new(),
                    command: String::new(),
                });
            }
            continue;
        }

        if line.starts_with("## ") && headline.is_empty() {
            headline = line.trim_start_matches("## ").trim().to_string();
            in_body = true;
            continue;
        }

        if line.starts_with("## ") && !headline.is_empty() {
            in_body = false;
            continue;
        }

        if in_body {
            body.push_str(line);
            body.push('\n');
        }

        if in_actions {
            if line.starts_with("- **") {
                // Flush previous
                if let Some((pri, act)) = current_action.take() {
                    action_items.push(ActionItem {
                        priority: pri,
                        action: act,
                        reason: String::new(),
                        command: String::new(),
                    });
                }

                // Parse priority icon
                let priority = if line.contains("!!") {
                    "critical"
                } else if line.contains("! ") {
                    "high"
                } else {
                    "medium"
                };

                // Extract action text after **...**
                let action_text = line
                    .split("**")
                    .nth(2)
                    .unwrap_or("")
                    .trim()
                    .to_string();
                current_action = Some((priority.to_string(), action_text));
            } else if line.starts_with("  - ") && current_action.is_some() {
                // Sub-bullet: reason or command
                let sub = line.trim_start_matches("  - ").trim();
                if let Some(ref mut action_pair) = current_action {
                    // Peek at last pushed action and update it
                    if sub.starts_with('`') {
                        // It's a command hint — push the action with this command
                        let cmd = sub.trim_matches('`').to_string();
                        action_items.push(ActionItem {
                            priority: action_pair.0.clone(),
                            action: action_pair.1.clone(),
                            reason: String::new(),
                            command: cmd,
                        });
                        current_action = None;
                    }
                }
            }
        }
    }

    // Flush last action
    if let Some((pri, act)) = current_action {
        action_items.push(ActionItem {
            priority: pri,
            action: act,
            reason: String::new(),
            command: String::new(),
        });
    }

    if headline.is_empty() && body.is_empty() {
        return None;
    }

    Some(BriefingData {
        headline,
        generated_at,
        body: body.trim().to_string(),
        action_items,
    })
}

// --- Helpers ---

fn expand_home(path: &str) -> String {
    if path.starts_with("~/") {
        if let Ok(home) = std::env::var("HOME") {
            return format!("{}{}", home, &path[1..]);
        }
    }
    path.to_string()
}
