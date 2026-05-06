# Slint Logos Spike

Standalone feasibility spike for a native Logos client surface. It is
intentionally isolated from `hapax-logos` and production services.

## Run

```bash
cargo run --release
```

The client defaults to:

```text
http://127.0.0.1:8051/api/health
```

Override the endpoint with `LOGOS_API_URL`.

For the resource profile measured in the research note, force Slint's
software backend:

```bash
SLINT_BACKEND=winit-software \
LOGOS_API_URL=http://127.0.0.1:8051/api/health \
cargo run --release
```

The binary prints `TTFP_PROXY_MS` when Slint's event loop first services
the app window and `HEALTH_FETCH_STATUS` after the health request
returns.
