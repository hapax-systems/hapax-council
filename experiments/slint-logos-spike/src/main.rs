use std::thread;
use std::time::Instant;

slint::include_modules!();

const DEFAULT_ENDPOINT: &str = "http://127.0.0.1:8051/api/health";

fn main() -> Result<(), slint::PlatformError> {
    let endpoint = std::env::var("LOGOS_API_URL").unwrap_or_else(|_| DEFAULT_ENDPOINT.to_string());
    let started = Instant::now();
    let app = AppWindow::new()?;

    app.set_endpoint(endpoint.clone().into());
    app.set_status_text("Waiting for first health fetch...".into());

    let refresh_target = app.as_weak();
    app.on_refresh({
        let endpoint = endpoint.clone();
        move || {
            spawn_health_fetch(refresh_target.clone(), endpoint.clone());
        }
    });

    let first_paint_target = app.as_weak();
    let _ = slint::invoke_from_event_loop(move || {
        println!("TTFP_PROXY_MS={}", started.elapsed().as_millis());
        if let Some(app) = first_paint_target.upgrade() {
            app.invoke_refresh();
        }
    });

    app.run()
}

fn spawn_health_fetch(app: slint::Weak<AppWindow>, endpoint: String) {
    thread::spawn(move || {
        let message = match fetch_health(&endpoint) {
            Ok(body) => format_health_body(&body),
            Err(err) => format!("fetch failed: {err}"),
        };

        let _ = slint::invoke_from_event_loop(move || {
            if let Some(app) = app.upgrade() {
                app.set_status_text(message.into());
            }
        });
    });
}

fn fetch_health(endpoint: &str) -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;

    runtime.block_on(async move {
        let response = reqwest::get(endpoint).await?;
        let status = response.status();
        let body = response.text().await?;
        println!("HEALTH_FETCH_STATUS={status} BODY_BYTES={}", body.len());
        Ok(format!("HTTP {status}\n{body}"))
    })
}

fn format_health_body(body: &str) -> String {
    const LIMIT: usize = 900;
    if body.len() <= LIMIT {
        return body.to_string();
    }

    let mut truncated = body[..LIMIT].to_string();
    truncated.push_str("\n...");
    truncated
}
