use vergen_gitcl::{Emitter, GitclBuilder};

fn main() {
    let git = GitclBuilder::default()
        .sha(true)
        .dirty(true)
        .branch(true)
        .build()
        .unwrap();

    if let Err(e) = Emitter::default()
        .add_instructions(&git)
        .and_then(|e| e.emit())
    {
        eprintln!("cargo:warning=vergen failed: {e}");
        // Fallback: emit empty values so env!() doesn't fail
        println!("cargo:rustc-env=VERGEN_GIT_SHA=unknown");
        println!("cargo:rustc-env=VERGEN_GIT_DIRTY=unknown");
        println!("cargo:rustc-env=VERGEN_GIT_BRANCH=unknown");
    }

    // Build timestamp (no vergen needed)
    println!("cargo:rustc-env=VERGEN_BUILD_TIMESTAMP={}", chrono_now());

    tauri_build::build();
}

fn chrono_now() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    // ISO 8601 approximate
    format!("{}", secs)
}
