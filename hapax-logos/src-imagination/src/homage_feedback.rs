use serde::Serialize;
use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

const SHADER_READING_PATH: &str = "/dev/shm/hapax-compositor/homage-shader-reading.json";

#[derive(Serialize)]
struct ShaderCouplingReading {
    timestamp: f64,
    shader_energy: f64,
    shader_drift: f64,
    substrate_fresh: bool,
}

pub fn emit_shader_feedback(energy: f64, drift: f64, is_fresh: bool) {
    let now = match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(n) => n.as_secs_f64(),
        Err(_) => 0.0,
    };

    let reading = ShaderCouplingReading {
        timestamp: now,
        shader_energy: energy.clamp(0.0, 1.0),
        shader_drift: drift.clamp(0.0, 1.0),
        substrate_fresh: is_fresh,
    };

    if let Ok(json) = serde_json::to_string(&reading) {
        let path = Path::new(SHADER_READING_PATH);
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }

        let tmp_path = path.with_extension("tmp");
        if let Ok(mut file) = File::create(&tmp_path) {
            if file.write_all(json.as_bytes()).is_ok() {
                let _ = std::fs::rename(tmp_path, path);
            }
        }
    }
}
