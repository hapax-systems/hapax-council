//! Agent-controlled browser via chromiumoxide (CDP).
//!
//! Hapax uses a headless Chromium instance to interact with web content
//! on behalf of agents. The browser is never operator-facing — it's Hapax's
//! tool for web interaction (GitHub PRs, Grafana boards, Langfuse traces, etc.).

pub mod a11y;
pub mod commands;
pub mod engine;
pub mod services;
