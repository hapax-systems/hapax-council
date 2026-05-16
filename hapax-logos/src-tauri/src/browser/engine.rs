//! Browser lifecycle: spawn headless Chromium, manage pages, shutdown.
//!
//! The browser persists across agent requests using a shared profile dir
//! at ~/.hapax/browser-profile/ so cookies/sessions survive restarts.

use std::path::PathBuf;
use std::sync::Arc;

use chromiumoxide::browser::{Browser, BrowserConfig};
use chromiumoxide::Page;
use futures::StreamExt;
use tokio::sync::Mutex;

/// Shared browser state accessible from Tauri commands and directive watcher.
pub struct BrowserEngine {
    browser: Browser,
    /// Single active page — reused across navigations for simplicity.
    page: Mutex<Option<Page>>,
    /// Handler join handle — dropping this kills the CDP connection.
    _handler: tokio::task::JoinHandle<()>,
}

impl BrowserEngine {
    /// Spawn a headless Chromium with persistent profile.
    pub async fn launch() -> Result<Arc<Self>, Box<dyn std::error::Error + Send + Sync>> {
        let profile_dir = profile_path();
        std::fs::create_dir_all(&profile_dir).ok();

        let config = BrowserConfig::builder()
            .user_data_dir(&profile_dir)
            .arg("--disable-gpu")
            .arg("--no-first-run")
            .arg("--disable-default-apps")
            .arg("--disable-extensions")
            .arg("--disable-sync")
            .build()
            .map_err(|e| format!("BrowserConfig error: {e}"))?;

        let (browser, mut handler) = Browser::launch(config).await?;

        let handle = tokio::spawn(async move {
            while let Some(h) = handler.next().await {
                if h.is_err() {
                    break;
                }
            }
        });

        log::info!(
            "Browser engine launched (headless, profile: {:?})",
            profile_dir
        );

        Ok(Arc::new(Self {
            browser,
            page: Mutex::new(None),
            _handler: handle,
        }))
    }

    /// Get or create the active page.
    pub async fn active_page(&self) -> Result<Page, String> {
        let mut guard = self.page.lock().await;
        if let Some(ref page) = *guard {
            return Ok(page.clone());
        }
        let page = self
            .browser
            .new_page("about:blank")
            .await
            .map_err(|e| format!("Failed to create page: {e}"))?;
        *guard = Some(page.clone());
        Ok(page)
    }

    /// Navigate the active page to a URL.
    pub async fn navigate(&self, url: &str) -> Result<String, String> {
        let page = self.active_page().await?;
        page.goto(url)
            .await
            .map_err(|e| format!("Navigation failed: {e}"))?;
        let title = page
            .evaluate("document.title")
            .await
            .ok()
            .and_then(|v| v.into_value::<String>().ok())
            .unwrap_or_default();
        Ok(title)
    }

    /// Evaluate JavaScript on the active page.
    pub async fn eval(&self, expression: &str) -> Result<serde_json::Value, String> {
        let page = self.active_page().await?;
        let result = page
            .evaluate(expression)
            .await
            .map_err(|e| format!("Eval failed: {e}"))?;
        Ok(result.value().cloned().unwrap_or(serde_json::Value::Null))
    }

    /// Take a screenshot of the active page, returns base64-encoded PNG.
    pub async fn screenshot(&self) -> Result<String, String> {
        use base64::Engine;
        use chromiumoxide::cdp::browser_protocol::page::CaptureScreenshotFormat;
        use chromiumoxide::page::ScreenshotParams;

        let page = self.active_page().await?;
        let bytes = page
            .screenshot(
                ScreenshotParams::builder()
                    .format(CaptureScreenshotFormat::Png)
                    .full_page(true)
                    .build(),
            )
            .await
            .map_err(|e| format!("Screenshot failed: {e}"))?;
        Ok(base64::engine::general_purpose::STANDARD.encode(&bytes))
    }

    /// Get current URL.
    pub async fn get_url(&self) -> Result<String, String> {
        let page = self.active_page().await?;
        page.url()
            .await
            .map_err(|e| format!("get_url failed: {e}"))
            .map(|u| u.unwrap_or_default().to_string())
    }

    /// Get page title.
    pub async fn get_title(&self) -> Result<String, String> {
        let page = self.active_page().await?;
        let title: String = page
            .evaluate("document.title")
            .await
            .map_err(|e| format!("get_title failed: {e}"))?
            .into_value()
            .unwrap_or_default();
        Ok(title)
    }

    /// Click an element by CSS selector.
    pub async fn click(&self, selector: &str) -> Result<(), String> {
        let page = self.active_page().await?;
        page.find_element(selector)
            .await
            .map_err(|e| format!("Element not found '{selector}': {e}"))?
            .click()
            .await
            .map_err(|e| format!("Click failed on '{selector}': {e}"))?;
        Ok(())
    }

    /// Fill a form field by CSS selector.
    pub async fn fill(&self, selector: &str, text: &str) -> Result<(), String> {
        let page = self.active_page().await?;
        page.find_element(selector)
            .await
            .map_err(|e| format!("Element not found '{selector}': {e}"))?
            .click()
            .await
            .map_err(|e| format!("Focus failed on '{selector}': {e}"))?
            .type_str(text)
            .await
            .map_err(|e| format!("Type failed on '{selector}': {e}"))?;
        Ok(())
    }

    /// Press a key (e.g. "Enter", "Tab", "Escape").
    pub async fn press_key(&self, key: &str) -> Result<(), String> {
        use chromiumoxide::cdp::browser_protocol::input::{
            DispatchKeyEventParams, DispatchKeyEventType,
        };
        let page = self.active_page().await?;
        // Key down
        let down = DispatchKeyEventParams::builder()
            .r#type(DispatchKeyEventType::KeyDown)
            .key(key)
            .build()
            .unwrap();
        page.execute(down)
            .await
            .map_err(|e| format!("press_key down failed: {e}"))?;
        // Key up
        let up = DispatchKeyEventParams::builder()
            .r#type(DispatchKeyEventType::KeyUp)
            .key(key)
            .build()
            .unwrap();
        page.execute(up)
            .await
            .map_err(|e| format!("press_key up failed: {e}"))?;
        Ok(())
    }

    /// Shutdown the browser.
    #[allow(dead_code)]
    pub async fn close(&self) -> Result<(), String> {
        // Browser::close is not &self, so we just log.
        // The handler task will exit when the browser process dies.
        log::info!("Browser engine shutdown requested");
        Ok(())
    }
}

fn profile_path() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("/tmp"))
        .join(".hapax")
        .join("browser-profile")
}
