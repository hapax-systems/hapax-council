//! Service registry — maps service names to base URLs and URL templates.
//!
//! Acts as an allowlist: only registered domains are permitted for browser
//! navigation. Enforces the corporate_boundary axiom.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;

/// A registered service with URL patterns.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceEntry {
    pub base: String,
    pub patterns: HashMap<String, String>,
    #[serde(default)]
    pub default_repo: Option<String>,
}

/// The full service registry.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ServiceRegistry {
    #[serde(flatten)]
    pub services: HashMap<String, ServiceEntry>,
}

impl ServiceRegistry {
    /// Load from ~/.hapax/browser-services.json (or return empty if missing).
    pub fn load() -> Self {
        let path = registry_path();
        match std::fs::read_to_string(&path) {
            Ok(contents) => serde_json::from_str(&contents).unwrap_or_else(|e| {
                log::warn!("Failed to parse browser-services.json: {}", e);
                Self::default()
            }),
            Err(_) => {
                log::info!(
                    "No browser-services.json at {:?}, creating default",
                    path
                );
                let registry = Self::create_default();
                if let Ok(json) = serde_json::to_string_pretty(&registry) {
                    std::fs::create_dir_all(path.parent().unwrap()).ok();
                    std::fs::write(&path, json).ok();
                }
                registry
            }
        }
    }

    /// Check if a URL is within an allowlisted service domain.
    pub fn is_allowed(&self, url: &str) -> bool {
        self.services.values().any(|svc| url.starts_with(&svc.base))
    }

    /// Resolve a service + pattern + params to a full URL.
    pub fn resolve(
        &self,
        service: &str,
        pattern: &str,
        params: &HashMap<String, String>,
    ) -> Option<String> {
        let svc = self.services.get(service)?;
        let template = svc.patterns.get(pattern)?;

        let mut url = format!("{}{}", svc.base, template);
        for (key, value) in params {
            url = url.replace(&format!("{{{key}}}"), value);
        }

        // Fill in defaults
        if let Some(ref repo) = svc.default_repo {
            url = url.replace("{repo}", repo);
        }

        Some(url)
    }

    fn create_default() -> Self {
        let mut services = HashMap::new();

        services.insert(
            "github".to_string(),
            ServiceEntry {
                base: "https://github.com/ryanklee".to_string(),
                patterns: HashMap::from([
                    ("pr".to_string(), "/{repo}/pull/{id}".to_string()),
                    ("issue".to_string(), "/{repo}/issues/{id}".to_string()),
                    ("repo".to_string(), "/{repo}".to_string()),
                ]),
                default_repo: Some("hapax-council".to_string()),
            },
        );

        services.insert(
            "grafana".to_string(),
            ServiceEntry {
                base: "http://localhost:3000".to_string(),
                patterns: HashMap::from([
                    ("board".to_string(), "/d/{id}".to_string()),
                    ("explore".to_string(), "/explore".to_string()),
                ]),
                default_repo: None,
            },
        );

        services.insert(
            "langfuse".to_string(),
            ServiceEntry {
                base: "http://localhost:3000".to_string(),
                patterns: HashMap::from([
                    (
                        "traces".to_string(),
                        "/project/{project}/traces".to_string(),
                    ),
                    (
                        "dashboard".to_string(),
                        "/project/{project}/dashboard".to_string(),
                    ),
                ]),
                default_repo: None,
            },
        );

        Self { services }
    }
}

fn registry_path() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("/tmp"))
        .join(".hapax")
        .join("browser-services.json")
}

// ─── Tauri command ────────────────────────────────────────────────────────────

/// Return the service registry as JSON.
#[tauri::command]
pub fn browser_get_services() -> serde_json::Value {
    let registry = ServiceRegistry::load();
    serde_json::to_value(registry).unwrap_or(serde_json::Value::Null)
}

/// Resolve a service reference to a URL.
#[tauri::command]
pub fn browser_resolve_url(
    service: String,
    pattern: String,
    params: HashMap<String, String>,
) -> Result<String, String> {
    let registry = ServiceRegistry::load();
    registry
        .resolve(&service, &pattern, &params)
        .ok_or_else(|| format!("Cannot resolve {service}/{pattern}"))
}
