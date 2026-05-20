use std::process::ExitCode;

fn main() -> ExitCode {
    eprintln!(
        "hapax-logos native Tauri shell is decommissioned; use the browser UI \
         and logos-api on :8051. See docs/runbooks/tauri-logos-decommission.md."
    );
    ExitCode::from(78)
}
