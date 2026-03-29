use vergen_gitcl::{Emitter, GitclBuilder};

fn main() {
    let git = GitclBuilder::default()
        .sha(true)
        .dirty(true)
        .build()
        .unwrap();

    if let Err(e) = Emitter::default()
        .add_instructions(&git)
        .and_then(|e| e.emit())
    {
        eprintln!("cargo:warning=vergen failed: {e}");
        println!("cargo:rustc-env=VERGEN_GIT_SHA=unknown");
    }

    // Build timestamp
    println!(
        "cargo:rustc-env=VERGEN_BUILD_TIMESTAMP={}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs()
    );
}
