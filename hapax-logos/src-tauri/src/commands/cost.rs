use serde::{Deserialize, Serialize};

const LANGFUSE_URL: &str = "http://127.0.0.1:3000";

#[derive(Debug, Clone, Serialize)]
pub struct CostSnapshot {
    pub today_cost: f64,
    pub period_cost: f64,
    pub daily_average: f64,
    pub top_models: Vec<ModelCost>,
    pub available: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct ModelCost {
    pub model: String,
    pub cost: f64,
}

#[derive(Deserialize)]
struct LangfuseResponse {
    #[serde(default)]
    data: Vec<LangfuseObservation>,
}

#[derive(Deserialize)]
struct LangfuseObservation {
    #[serde(default)]
    model: Option<String>,
    #[serde(default, rename = "calculatedTotalCost")]
    calculated_total_cost: Option<f64>,
    #[serde(default, rename = "startTime")]
    start_time: Option<String>,
}

#[tauri::command]
pub async fn get_cost() -> CostSnapshot {
    match fetch_cost().await {
        Ok(snapshot) => snapshot,
        Err(e) => {
            log::warn!("Langfuse cost fetch failed: {}", e);
            CostSnapshot {
                today_cost: 0.0,
                period_cost: 0.0,
                daily_average: 0.0,
                top_models: vec![],
                available: false,
            }
        }
    }
}

async fn fetch_cost() -> Result<CostSnapshot, String> {
    let client = reqwest::Client::new();

    // Get observations from last 7 days
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let seven_days_ago = now - 7 * 86400;
    let from_time = format_iso(seven_days_ago);
    let today_start = format_iso(now - (now % 86400));

    let url = format!(
        "{}/api/public/observations?type=GENERATION&fromStartTime={}&limit=1000",
        LANGFUSE_URL, from_time
    );

    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("HTTP error: {}", e))?;

    if !resp.status().is_success() {
        return Err(format!("Langfuse returned {}", resp.status()));
    }

    let data: LangfuseResponse = resp
        .json()
        .await
        .map_err(|e| format!("JSON parse error: {}", e))?;

    let mut period_cost = 0.0;
    let mut today_cost = 0.0;
    let mut model_costs: std::collections::HashMap<String, f64> = std::collections::HashMap::new();

    for obs in &data.data {
        let cost = obs.calculated_total_cost.unwrap_or(0.0);
        period_cost += cost;

        if let Some(ref model) = obs.model {
            *model_costs.entry(model.clone()).or_default() += cost;
        }

        if let Some(ref start) = obs.start_time {
            if start.as_str() >= today_start.as_str() {
                today_cost += cost;
            }
        }
    }

    let daily_average = period_cost / 7.0;

    let mut top_models: Vec<ModelCost> = model_costs
        .into_iter()
        .map(|(model, cost)| ModelCost { model, cost })
        .collect();
    top_models.sort_by(|a, b| b.cost.partial_cmp(&a.cost).unwrap_or(std::cmp::Ordering::Equal));
    top_models.truncate(5);

    Ok(CostSnapshot {
        today_cost,
        period_cost,
        daily_average,
        top_models,
        available: true,
    })
}

fn format_iso(epoch_secs: u64) -> String {
    let days = (epoch_secs / 86400) as i64;
    let remaining = epoch_secs % 86400;
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z.rem_euclid(146097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        y, m, d,
        remaining / 3600,
        (remaining % 3600) / 60,
        remaining % 60
    )
}
