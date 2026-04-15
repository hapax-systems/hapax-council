# Prometheus + Grafana Dashboards Catalog

Generated: 2026-04-15

## Active Dashboards

### 1. Hapax — Operational Health
- **UID:** `hapax-operational-health`
- **Updated:** 2026-04-03
- **Audience:** Operator (Critical)
- **Primary Metrics:**
  - `hapax_mesh_error`
  - `hapax_mesh_perception`
  - `hapax_stimmung_value` / `stance`
  - `hapax_cpal_error` / `gain`
  - `hapax_exploration_boredom` / `curiosity`
  - `hapax_dmn_buffer_entries`
- **Notes:** High-level system health monitoring.

### 2. Hapax — Behavioral Predictions
- **UID:** `hapax-behavioral-predictions`
- **Updated:** 2026-04-03
- **Audience:** Research / Operator
- **Primary Metrics:**
  - `hapax_hebbian_associations`
  - `hapax_imagination_salience`
  - `hapax_capability_uses`
  - `hapax_thompson_mean`
  - `reverie_prediction_actual`
- **Notes:** Tracks long-term behavioral trends and cognitive associations.

### 3. Reverie — Prediction Monitor
- **UID:** `reverie-predictions`
- **Updated:** 2026-04-03
- **Audience:** Research (Specialized)
- **Primary Metrics:**
  - `reverie_prediction_actual{prediction="P1..P6"}`
  - `reverie_presence_signal` / `posterior`
  - `reverie_technique_confidence` / `rate`
  - `reverie_uniform_deviation`
- **Notes:** Specialized monitor for the Reverie visual surface and behavioral predictions (from PR #570).

## Stale / Internal Dashboards
- **hapax-alerts (Folder):** Contains alert-specific views.

## Summary of Findings
- **Total Dashboards:** 3 primary, 1 folder.
- **Metric Coverage:** Good coverage of Mesh, Stimmung, CPAL, and Reverie subsystems.
- **Audience:** Primarily operator-facing with a research focus on predictions.
- **Staleness:** All dashboards were last updated on 2026-04-03. They appear active but haven't had structural changes in 12 days.
