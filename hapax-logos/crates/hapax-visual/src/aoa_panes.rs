//! Aperture of Apertures pane registry.
//!
//! This module is the Rust-side authority for AoA pane identity. The WGSL
//! shader still renders the panes, but it should mirror this lineage/ordinal
//! contract rather than being the only place where pane identity exists.

use glam::{Mat4, Vec2, Vec3, Vec4};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

pub const AOA_OBJECT_ID: &str = "aperture-of-apertures";
pub const AOA_GEOMETRY_REVISION: &str = "aoa-regular-tetrix-v4-perfect-fit-oarb";
pub const AOA_PANE_SCHEMA_VERSION: u32 = 1;
pub const AOA_PANE_ID_VERSION: &str = "v1";
pub const AOA_TETRIX_RENDER_DEPTH: u32 = 4;
pub const AOA_LEAF_FACE_EDGE_UNITS: u32 = 48;
pub const AOA_PARENT_EDGE_UNITS: u32 = AOA_LEAF_FACE_EDGE_UNITS * (1 << AOA_TETRIX_RENDER_DEPTH);
pub const AOA_OARB_INNER_VOID_RADIUS_FILL_RATIO: f32 = 1.0;
pub const AOA_PANE_CLIP_TOLERANCE: f32 = 0.001;
pub const AOA_PANE_MIN_VISIBLE_EDGE_PX: f32 = 4.0;
pub const AOA_PANE_MIN_FRONT_FACING_DOT: f32 = 0.02;
pub const AOA_PANE_LOD_HYSTERESIS_RATIO: f32 = 0.12;
pub const AOA_PANE_LOD_MIN_DWELL_MS: u32 = 500;
pub const AOA_PANE_TEXT_AREA_PX2: f32 = 10_000.0;
pub const AOA_PANE_TEXT_MIN_EDGE_PX: f32 = 80.0;
pub const AOA_PANE_TEXT_MIN_FACING_DOT: f32 = 0.25;
pub const AOA_PANE_TEXT_MIN_VISIBLE_FRACTION: f32 = 0.80;
pub const AOA_PANE_COMPACT_AREA_PX2: f32 = 4_000.0;
pub const AOA_PANE_COMPACT_MIN_EDGE_PX: f32 = 48.0;
pub const AOA_PANE_COMPACT_MIN_FACING_DOT: f32 = 0.20;
pub const AOA_PANE_COMPACT_MIN_VISIBLE_FRACTION: f32 = 0.70;
pub const AOA_PANE_GLYPH_AREA_PX2: f32 = 1_200.0;
pub const AOA_PANE_GLYPH_MIN_EDGE_PX: f32 = 24.0;
pub const AOA_PANE_GLYPH_MIN_VISIBLE_FRACTION: f32 = 0.60;
pub const AOA_PANE_ACCENT_AREA_PX2: f32 = 300.0;
pub const AOA_PANE_ACCENT_MIN_EDGE_PX: f32 = 10.0;
const AOA_CLIP_W_EPSILON: f32 = 0.000_001;
const AOA_PANE_CLIPPED_UNKNOWN_VISIBLE_FRACTION: f32 = 0.5;

pub const AOA_ROOT_EDGE: f32 = 1.0;
pub const AOA_ROOT_INRADIUS: f32 = 0.204_124_15;
pub const AOA_ROOT_BASE_RADIUS: f32 = 0.577_350_26;

pub const AOA_ROOT_MODEL_VERTICES: [[f32; 3]; 4] = [
    [-0.5, -AOA_ROOT_INRADIUS, -AOA_ROOT_BASE_RADIUS / 2.0],
    [0.5, -AOA_ROOT_INRADIUS, -AOA_ROOT_BASE_RADIUS / 2.0],
    [0.0, -AOA_ROOT_INRADIUS, AOA_ROOT_BASE_RADIUS],
    [0.0, AOA_ROOT_INRADIUS * 3.0, 0.0],
];

pub const AOA_ROOT_BARY4_VERTICES: [[f32; 4]; 4] = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AoaChild {
    A,
    B,
    C,
    D,
}

impl AoaChild {
    pub fn from_digit(digit: u32) -> Option<Self> {
        match digit {
            0 => Some(Self::A),
            1 => Some(Self::B),
            2 => Some(Self::C),
            3 => Some(Self::D),
            _ => None,
        }
    }

    pub fn digit(self) -> u32 {
        match self {
            Self::A => 0,
            Self::B => 1,
            Self::C => 2,
            Self::D => 3,
        }
    }

    pub fn key(self) -> &'static str {
        match self {
            Self::A => "a",
            Self::B => "b",
            Self::C => "c",
            Self::D => "d",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AoaFaceKey {
    Abd,
    Bcd,
    Cad,
    Acb,
}

impl AoaFaceKey {
    pub fn from_index(index: u32) -> Option<Self> {
        match index {
            0 => Some(Self::Abd),
            1 => Some(Self::Bcd),
            2 => Some(Self::Cad),
            3 => Some(Self::Acb),
            _ => None,
        }
    }

    pub fn index(self) -> u32 {
        match self {
            Self::Abd => 0,
            Self::Bcd => 1,
            Self::Cad => 2,
            Self::Acb => 3,
        }
    }

    pub fn key(self) -> &'static str {
        match self {
            Self::Abd => "abd",
            Self::Bcd => "bcd",
            Self::Cad => "cad",
            Self::Acb => "acb",
        }
    }

    pub fn corner_indices(self) -> [usize; 3] {
        match self {
            // Must match scene_quad.wgsl::aoa_face_vertex.
            Self::Abd => [0, 1, 3],
            Self::Bcd => [1, 2, 3],
            Self::Cad => [2, 0, 3],
            Self::Acb => [0, 2, 1],
        }
    }

    pub fn corner_order(self) -> [&'static str; 3] {
        match self {
            Self::Abd => ["a", "b", "d"],
            Self::Bcd => ["b", "c", "d"],
            Self::Cad => ["c", "a", "d"],
            Self::Acb => ["a", "c", "b"],
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaBoundaryRole {
    RootHull,
    HullSubface,
    VoidWall,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPaneBindingMode {
    EdgeAccent,
    SignalGlyph,
    DataGlyph,
    TriTextureMasked,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaMaxDensity {
    None,
    Accent,
    Glyph,
    CompactData,
    Text,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPanePrivacyClass {
    PublicSafe,
    PrivateOnly,
    Blocked,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AoaContentEligibility {
    pub allowed_modes: Vec<AoaPaneBindingMode>,
    pub max_density: AoaMaxDensity,
    pub privacy_class: AoaPanePrivacyClass,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AoaPaneRecord {
    pub schema_version: u32,
    pub object_id: String,
    pub geometry_revision: String,
    pub pane_id: String,
    pub pane_ordinal: u32,
    pub depth: u32,
    pub lineage_path: Vec<AoaChild>,
    pub lineage_digits: Vec<u32>,
    pub tetra_id: String,
    pub parent_tetra_id: Option<String>,
    pub face_key: AoaFaceKey,
    pub face_index: u32,
    pub corner_order: Vec<String>,
    pub child_rule: String,
    pub boundary_role: AoaBoundaryRole,
    pub root_bary4_vertices: [[f32; 4]; 3],
    pub model_vertices: [[f32; 3]; 3],
    pub centroid_model: [f32; 3],
    pub normal_model: [f32; 3],
    pub ancestor_pane_ids: Vec<String>,
    pub semantic_slot: Option<String>,
    pub content_eligibility: AoaContentEligibility,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AoaPaneManifest {
    pub schema_version: u32,
    pub object_id: String,
    pub geometry_revision: String,
    pub render_depth: u32,
    pub pane_count: usize,
    pub panes: Vec<AoaPaneRecord>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPanePayloadBlockReason {
    MissingPaneBinding,
    MissingPaneTransform,
    MissingBarycentricMask,
    PaneHidden,
    BackFacing,
    BelowVisibilityThreshold,
    OutsideTriangle,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AoaPanePayloadGate {
    pub has_valid_pane_binding: bool,
    pub has_pane_transform: bool,
    pub has_barycentric_mask: bool,
    pub pane_visible: bool,
    pub facing_dot: f32,
    pub min_projected_edge_px: f32,
    pub barycentric: [f32; 3],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPaneLodClass {
    Culled,
    EdgeOnly,
    Accent,
    Glyph,
    CompactData,
    Text,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPaneOcclusionState {
    Visible,
    Partial,
    Hidden,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPaneObservationGateReason {
    NonFiniteProjection,
    BehindCamera,
    Offscreen,
    BackFacing,
    Tiny,
    MinimumDwellHold,
    HysteresisHold,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AoaPaneLodConfig {
    pub hysteresis_ratio: f32,
    pub min_dwell_ms: u32,
}

impl Default for AoaPaneLodConfig {
    fn default() -> Self {
        Self {
            hysteresis_ratio: AOA_PANE_LOD_HYSTERESIS_RATIO,
            min_dwell_ms: AOA_PANE_LOD_MIN_DWELL_MS,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AoaPaneObservationMetrics {
    pub projected_area_px2: f32,
    pub min_projected_edge_px: f32,
    pub facing_dot: f32,
    pub visible_fraction: f32,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AoaPaneObservationFrame {
    pub model_matrix: Mat4,
    pub view_projection_matrix: Mat4,
    pub camera_eye: Vec3,
    pub viewport_px: [u32; 2],
}

impl AoaPaneObservationFrame {
    pub fn new(
        model_matrix: Mat4,
        view_matrix: Mat4,
        projection_matrix: Mat4,
        camera_eye: Vec3,
        viewport_width: u32,
        viewport_height: u32,
    ) -> Self {
        Self {
            model_matrix,
            view_projection_matrix: projection_matrix * view_matrix,
            camera_eye,
            viewport_px: [viewport_width, viewport_height],
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AoaPaneFrameObservation {
    pub pane_id: String,
    pub pane_ordinal: u32,
    pub viewport_px: [u32; 2],
    pub screen_bbox_px: [f32; 4],
    pub projected_area_px2: f32,
    pub min_projected_edge_px: f32,
    pub facing_dot: f32,
    pub visible_fraction: f32,
    pub occlusion_state: AoaPaneOcclusionState,
    pub lod_class: AoaPaneLodClass,
    pub gate_reasons: Vec<AoaPaneObservationGateReason>,
}

impl AoaPaneFrameObservation {
    pub fn metrics(&self) -> AoaPaneObservationMetrics {
        AoaPaneObservationMetrics {
            projected_area_px2: self.projected_area_px2,
            min_projected_edge_px: self.min_projected_edge_px,
            facing_dot: self.facing_dot,
            visible_fraction: self.visible_fraction,
        }
    }
}

impl AoaPanePayloadGate {
    pub fn visible_inside(barycentric: [f32; 3]) -> Self {
        Self {
            has_valid_pane_binding: true,
            has_pane_transform: true,
            has_barycentric_mask: true,
            pane_visible: true,
            facing_dot: 1.0,
            min_projected_edge_px: AOA_PANE_MIN_VISIBLE_EDGE_PX,
            barycentric,
        }
    }
}

pub fn aoa_leaf_tetrahedron_count(depth: u32) -> usize {
    4usize.pow(depth)
}

pub fn aoa_total_tetrahedron_count(depth: u32) -> usize {
    (0..=depth).map(aoa_leaf_tetrahedron_count).sum()
}

pub fn aoa_raw_edge_segment_count(depth: u32) -> usize {
    aoa_leaf_tetrahedron_count(depth) * 6
}

pub fn aoa_raw_triangular_pane_count(depth: u32) -> usize {
    aoa_leaf_tetrahedron_count(depth) * 4
}

pub fn aoa_pane_start_ordinal(depth: u32) -> u32 {
    let _ = depth;
    0
}

pub fn aoa_tetra_index(lineage: &[AoaChild]) -> u32 {
    lineage
        .iter()
        .fold(0u32, |acc, child| acc * 4 + child.digit())
}

pub fn aoa_pane_ordinal(lineage: &[AoaChild], face_key: AoaFaceKey) -> u32 {
    aoa_pane_start_ordinal(lineage.len() as u32) + aoa_tetra_index(lineage) * 4 + face_key.index()
}

pub fn aoa_lineage_from_tetra_index(depth: u32, tetra_index: u32) -> Vec<AoaChild> {
    let mut lineage = Vec::with_capacity(depth as usize);
    for digit_pos in (0..depth).rev() {
        let digit = (tetra_index / 4u32.pow(digit_pos)) % 4;
        let child = AoaChild::from_digit(digit).expect("digit is modulo 4");
        lineage.push(child);
    }
    lineage
}

pub fn aoa_lineage_path_key(lineage: &[AoaChild]) -> String {
    if lineage.is_empty() {
        return "r".to_string();
    }
    lineage
        .iter()
        .map(|child| child.key())
        .collect::<Vec<_>>()
        .join(".")
}

pub fn aoa_pane_id(lineage: &[AoaChild], face_key: AoaFaceKey) -> String {
    format!(
        "aoa:pane:{AOA_PANE_ID_VERSION}:{}:{}",
        aoa_lineage_path_key(lineage),
        face_key.key()
    )
}

pub fn aoa_tetra_id(lineage: &[AoaChild]) -> String {
    format!(
        "aoa:tetra:{AOA_PANE_ID_VERSION}:{}",
        aoa_lineage_path_key(lineage)
    )
}

pub fn aoa_triangular_uv_from_barycentric(barycentric: [f32; 3]) -> [f32; 2] {
    [
        barycentric[1] + 0.5 * barycentric[2],
        (3.0f32).sqrt() * 0.5 * barycentric[2],
    ]
}

pub fn aoa_barycentric_inside_triangle(barycentric: [f32; 3], tolerance: f32) -> bool {
    if !barycentric.iter().all(|component| component.is_finite()) {
        return false;
    }
    let tolerance = tolerance.max(0.0);
    let sum = barycentric[0] + barycentric[1] + barycentric[2];
    (sum - 1.0).abs() <= tolerance * 3.0
        && barycentric.iter().all(|component| *component >= -tolerance)
}

pub fn aoa_pane_payload_alpha(source_alpha: f32, barycentric: [f32; 3], tolerance: f32) -> f32 {
    if !source_alpha.is_finite() {
        return 0.0;
    }
    if aoa_barycentric_inside_triangle(barycentric, tolerance) {
        source_alpha.clamp(0.0, 1.0)
    } else {
        0.0
    }
}

pub fn aoa_pane_payload_block_reason(
    gate: AoaPanePayloadGate,
) -> Option<AoaPanePayloadBlockReason> {
    if !gate.has_valid_pane_binding {
        return Some(AoaPanePayloadBlockReason::MissingPaneBinding);
    }
    if !gate.has_pane_transform {
        return Some(AoaPanePayloadBlockReason::MissingPaneTransform);
    }
    if !gate.has_barycentric_mask {
        return Some(AoaPanePayloadBlockReason::MissingBarycentricMask);
    }
    if !gate.pane_visible {
        return Some(AoaPanePayloadBlockReason::PaneHidden);
    }
    if !gate.facing_dot.is_finite() || gate.facing_dot < AOA_PANE_MIN_FRONT_FACING_DOT {
        return Some(AoaPanePayloadBlockReason::BackFacing);
    }
    if !gate.min_projected_edge_px.is_finite()
        || gate.min_projected_edge_px < AOA_PANE_MIN_VISIBLE_EDGE_PX
    {
        return Some(AoaPanePayloadBlockReason::BelowVisibilityThreshold);
    }
    if !aoa_barycentric_inside_triangle(gate.barycentric, AOA_PANE_CLIP_TOLERANCE) {
        return Some(AoaPanePayloadBlockReason::OutsideTriangle);
    }
    None
}

pub fn aoa_pane_payload_alpha_after_gate(source_alpha: f32, gate: AoaPanePayloadGate) -> f32 {
    if aoa_pane_payload_block_reason(gate).is_some() {
        0.0
    } else if !source_alpha.is_finite() {
        0.0
    } else {
        source_alpha.clamp(0.0, 1.0)
    }
}

pub fn aoa_observe_pane(
    pane: &AoaPaneRecord,
    frame: AoaPaneObservationFrame,
) -> AoaPaneFrameObservation {
    aoa_observe_pane_with_lod_state(pane, frame, None, AOA_PANE_LOD_MIN_DWELL_MS)
}

pub fn aoa_observe_pane_with_lod_state(
    pane: &AoaPaneRecord,
    frame: AoaPaneObservationFrame,
    previous_lod: Option<AoaPaneLodClass>,
    millis_since_lod_change: u32,
) -> AoaPaneFrameObservation {
    let projected = match project_pane_vertices(pane, frame) {
        Ok(projected) => projected,
        Err(reason) => {
            return empty_observation(pane, frame.viewport_px, reason);
        }
    };

    let screen_bbox_px = screen_bbox(&projected.screen_vertices);
    let projected_area_px2 = polygon_area_px2(&projected.screen_vertices);
    let visible_fraction = projected.visible_fraction(projected_area_px2);
    let min_projected_edge_px = min_edge_px(&projected.screen_vertices);
    let facing_dot = facing_dot(frame.camera_eye, projected.world_vertices);
    let metrics = AoaPaneObservationMetrics {
        projected_area_px2,
        min_projected_edge_px,
        facing_dot,
        visible_fraction,
    };

    let mut gate_reasons = observation_gate_reasons(metrics);
    let occlusion_state = if visible_fraction <= 0.0 {
        AoaPaneOcclusionState::Hidden
    } else if visible_fraction < 0.999 {
        AoaPaneOcclusionState::Partial
    } else {
        AoaPaneOcclusionState::Visible
    };
    let lod_class = aoa_lod_class_for_metrics_with_state(
        metrics,
        previous_lod,
        millis_since_lod_change,
        AoaPaneLodConfig::default(),
        &mut gate_reasons,
    );

    AoaPaneFrameObservation {
        pane_id: pane.pane_id.clone(),
        pane_ordinal: pane.pane_ordinal,
        viewport_px: frame.viewport_px,
        screen_bbox_px,
        projected_area_px2,
        min_projected_edge_px,
        facing_dot,
        visible_fraction,
        occlusion_state,
        lod_class,
        gate_reasons,
    }
}

pub fn aoa_observe_panes(
    panes: &[AoaPaneRecord],
    frame: AoaPaneObservationFrame,
) -> Vec<AoaPaneFrameObservation> {
    panes
        .iter()
        .map(|pane| aoa_observe_pane(pane, frame))
        .collect()
}

pub fn aoa_raw_lod_class_for_metrics(metrics: AoaPaneObservationMetrics) -> AoaPaneLodClass {
    if !metrics_are_finite(metrics)
        || metrics.visible_fraction <= 0.0
        || metrics.facing_dot < AOA_PANE_MIN_FRONT_FACING_DOT
        || metrics.min_projected_edge_px < AOA_PANE_MIN_VISIBLE_EDGE_PX
    {
        return AoaPaneLodClass::Culled;
    }
    for lod in [
        AoaPaneLodClass::Text,
        AoaPaneLodClass::CompactData,
        AoaPaneLodClass::Glyph,
        AoaPaneLodClass::Accent,
    ] {
        if metrics_support_lod(metrics, lod, 1.0) {
            return lod;
        }
    }
    AoaPaneLodClass::EdgeOnly
}

pub fn aoa_lod_class_for_metrics_with_state(
    metrics: AoaPaneObservationMetrics,
    previous_lod: Option<AoaPaneLodClass>,
    millis_since_lod_change: u32,
    config: AoaPaneLodConfig,
    gate_reasons: &mut Vec<AoaPaneObservationGateReason>,
) -> AoaPaneLodClass {
    let raw = aoa_raw_lod_class_for_metrics(metrics);
    let Some(previous) = previous_lod else {
        return raw;
    };
    if previous == raw || raw == AoaPaneLodClass::Culled {
        return raw;
    }
    if millis_since_lod_change < config.min_dwell_ms {
        gate_reasons.push(AoaPaneObservationGateReason::MinimumDwellHold);
        return previous;
    }
    if raw < previous
        && metrics_support_lod(
            metrics,
            previous,
            1.0 - config.hysteresis_ratio.clamp(0.0, 0.5),
        )
    {
        gate_reasons.push(AoaPaneObservationGateReason::HysteresisHold);
        return previous;
    }
    raw
}

pub fn aoa_min_lod_for_binding_mode(mode: AoaPaneBindingMode) -> AoaPaneLodClass {
    match mode {
        AoaPaneBindingMode::EdgeAccent => AoaPaneLodClass::Accent,
        AoaPaneBindingMode::SignalGlyph => AoaPaneLodClass::Glyph,
        AoaPaneBindingMode::DataGlyph => AoaPaneLodClass::CompactData,
        AoaPaneBindingMode::TriTextureMasked => AoaPaneLodClass::Text,
    }
}

pub fn aoa_pane_lod_supports_binding_mode(
    lod_class: AoaPaneLodClass,
    mode: AoaPaneBindingMode,
) -> bool {
    lod_class >= aoa_min_lod_for_binding_mode(mode)
}

pub fn aoa_pane_lod_alpha_for_binding_mode(
    observation: &AoaPaneFrameObservation,
    mode: AoaPaneBindingMode,
) -> f32 {
    if !aoa_pane_lod_supports_binding_mode(observation.lod_class, mode) {
        return 0.0;
    }
    let ratio = lod_metric_ratio(observation.metrics(), aoa_min_lod_for_binding_mode(mode));
    smoothstep(0.92, 1.08, ratio)
}

impl AoaPaneBindingMode {
    pub fn shader_payload_mode(self) -> f32 {
        match self {
            Self::EdgeAccent => 1.0,
            Self::SignalGlyph => 2.0,
            Self::DataGlyph => 3.0,
            Self::TriTextureMasked => 4.0,
        }
    }
}

pub fn aoa_pane_records(render_depth: u32) -> Vec<AoaPaneRecord> {
    let mut records = Vec::with_capacity(aoa_raw_triangular_pane_count(render_depth));
    for tetra_index in 0..aoa_leaf_tetrahedron_count(render_depth) as u32 {
        let lineage = aoa_lineage_from_tetra_index(render_depth, tetra_index);
        for face_index in 0..4 {
            let face_key = AoaFaceKey::from_index(face_index).expect("face index is 0..4");
            records.push(aoa_pane_record(&lineage, face_key));
        }
    }
    records
}

pub fn aoa_pane_manifest(render_depth: u32) -> AoaPaneManifest {
    let panes = aoa_pane_records(render_depth);
    AoaPaneManifest {
        schema_version: AOA_PANE_SCHEMA_VERSION,
        object_id: AOA_OBJECT_ID.to_string(),
        geometry_revision: AOA_GEOMETRY_REVISION.to_string(),
        render_depth,
        pane_count: panes.len(),
        panes,
    }
}

pub fn aoa_active_pane_manifest() -> AoaPaneManifest {
    aoa_pane_manifest(AOA_TETRIX_RENDER_DEPTH)
}

fn aoa_pane_record(lineage: &[AoaChild], face_key: AoaFaceKey) -> AoaPaneRecord {
    let (model_tetra, bary_tetra) = tetra_for_lineage(lineage);
    let corners = face_key.corner_indices();
    let model_vertices = corners.map(|idx| model_tetra[idx]);
    let root_bary4_vertices = corners.map(|idx| bary_tetra[idx]);
    let centroid = centroid(model_vertices);
    let normal = normal(model_vertices);
    let depth = lineage.len() as u32;
    let boundary_role = boundary_role(depth, root_bary4_vertices);

    AoaPaneRecord {
        schema_version: AOA_PANE_SCHEMA_VERSION,
        object_id: AOA_OBJECT_ID.to_string(),
        geometry_revision: AOA_GEOMETRY_REVISION.to_string(),
        pane_id: aoa_pane_id(lineage, face_key),
        pane_ordinal: aoa_pane_ordinal(lineage, face_key),
        depth,
        lineage_path: lineage.to_vec(),
        lineage_digits: lineage.iter().map(|child| child.digit()).collect(),
        tetra_id: aoa_tetra_id(lineage),
        parent_tetra_id: parent_tetra_id(lineage),
        face_key,
        face_index: face_key.index(),
        corner_order: face_key
            .corner_order()
            .into_iter()
            .map(str::to_string)
            .collect(),
        child_rule: "midpoint_contraction".to_string(),
        boundary_role,
        root_bary4_vertices,
        model_vertices,
        centroid_model: centroid.to_array(),
        normal_model: normal.to_array(),
        ancestor_pane_ids: ancestor_pane_ids(lineage, face_key),
        semantic_slot: None,
        content_eligibility: content_eligibility(depth, boundary_role),
    }
}

fn parent_tetra_id(lineage: &[AoaChild]) -> Option<String> {
    if lineage.is_empty() {
        None
    } else {
        Some(aoa_tetra_id(&lineage[..lineage.len() - 1]))
    }
}

fn ancestor_pane_ids(lineage: &[AoaChild], face_key: AoaFaceKey) -> Vec<String> {
    (0..lineage.len())
        .map(|prefix_len| aoa_pane_id(&lineage[..prefix_len], face_key))
        .collect()
}

fn content_eligibility(depth: u32, boundary_role: AoaBoundaryRole) -> AoaContentEligibility {
    let max_density = match boundary_role {
        AoaBoundaryRole::RootHull => AoaMaxDensity::Text,
        AoaBoundaryRole::HullSubface => AoaMaxDensity::CompactData,
        AoaBoundaryRole::VoidWall if depth >= AOA_TETRIX_RENDER_DEPTH => AoaMaxDensity::Glyph,
        AoaBoundaryRole::VoidWall => AoaMaxDensity::Accent,
    };
    let allowed_modes = match max_density {
        AoaMaxDensity::Text => vec![
            AoaPaneBindingMode::EdgeAccent,
            AoaPaneBindingMode::SignalGlyph,
            AoaPaneBindingMode::DataGlyph,
            AoaPaneBindingMode::TriTextureMasked,
        ],
        AoaMaxDensity::CompactData => vec![
            AoaPaneBindingMode::EdgeAccent,
            AoaPaneBindingMode::SignalGlyph,
            AoaPaneBindingMode::DataGlyph,
        ],
        AoaMaxDensity::Glyph => {
            vec![
                AoaPaneBindingMode::EdgeAccent,
                AoaPaneBindingMode::SignalGlyph,
            ]
        }
        AoaMaxDensity::Accent => vec![AoaPaneBindingMode::EdgeAccent],
        AoaMaxDensity::None => Vec::new(),
    };
    AoaContentEligibility {
        allowed_modes,
        max_density,
        privacy_class: AoaPanePrivacyClass::PublicSafe,
    }
}

fn tetra_for_lineage(lineage: &[AoaChild]) -> ([[f32; 3]; 4], [[f32; 4]; 4]) {
    let mut model_tetra = AOA_ROOT_MODEL_VERTICES;
    let mut bary_tetra = AOA_ROOT_BARY4_VERTICES;
    for child in lineage {
        model_tetra = child_tetra(model_tetra, child.digit() as usize);
        bary_tetra = child_tetra4(bary_tetra, child.digit() as usize);
    }
    (model_tetra, bary_tetra)
}

fn child_tetra(tetra: [[f32; 3]; 4], child_idx: usize) -> [[f32; 3]; 4] {
    let anchor = tetra[child_idx];
    tetra.map(|corner| mix3(anchor, corner, 0.5))
}

fn child_tetra4(tetra: [[f32; 4]; 4], child_idx: usize) -> [[f32; 4]; 4] {
    let anchor = tetra[child_idx];
    tetra.map(|corner| mix4(anchor, corner, 0.5))
}

fn mix3(a: [f32; 3], b: [f32; 3], t: f32) -> [f32; 3] {
    [
        a[0] * (1.0 - t) + b[0] * t,
        a[1] * (1.0 - t) + b[1] * t,
        a[2] * (1.0 - t) + b[2] * t,
    ]
}

fn mix4(a: [f32; 4], b: [f32; 4], t: f32) -> [f32; 4] {
    [
        a[0] * (1.0 - t) + b[0] * t,
        a[1] * (1.0 - t) + b[1] * t,
        a[2] * (1.0 - t) + b[2] * t,
        a[3] * (1.0 - t) + b[3] * t,
    ]
}

fn centroid(vertices: [[f32; 3]; 3]) -> Vec3 {
    (Vec3::from_array(vertices[0]) + Vec3::from_array(vertices[1]) + Vec3::from_array(vertices[2]))
        / 3.0
}

fn normal(vertices: [[f32; 3]; 3]) -> Vec3 {
    let a = Vec3::from_array(vertices[0]);
    let b = Vec3::from_array(vertices[1]);
    let c = Vec3::from_array(vertices[2]);
    (b - a).cross(c - a).normalize_or_zero()
}

fn boundary_role(depth: u32, bary_vertices: [[f32; 4]; 3]) -> AoaBoundaryRole {
    let lies_on_root_hull = (0..4).any(|component| {
        bary_vertices
            .iter()
            .all(|bary| bary[component].abs() < 0.000_001)
    });
    match (depth, lies_on_root_hull) {
        (0, _) => AoaBoundaryRole::RootHull,
        (_, true) => AoaBoundaryRole::HullSubface,
        _ => AoaBoundaryRole::VoidWall,
    }
}

pub fn aoa_manifest_has_unique_identity(manifest: &AoaPaneManifest) -> bool {
    let mut ids = HashSet::with_capacity(manifest.panes.len());
    let mut ordinals = HashSet::with_capacity(manifest.panes.len());
    manifest
        .panes
        .iter()
        .all(|pane| ids.insert(pane.pane_id.as_str()) && ordinals.insert(pane.pane_ordinal))
}

#[derive(Debug, Clone, Copy)]
struct ClipPaneVertex {
    clip: Vec4,
    world: Vec3,
}

#[derive(Debug, Clone)]
struct ProjectedPane {
    screen_vertices: Vec<Vec2>,
    world_vertices: [Vec3; 3],
    original_projected_area_px2: Option<f32>,
    was_clipped: bool,
}

impl ProjectedPane {
    fn visible_fraction(&self, projected_area_px2: f32) -> f32 {
        if projected_area_px2 <= 0.0 || !projected_area_px2.is_finite() {
            return 0.0;
        }
        if let Some(original_area) = self.original_projected_area_px2 {
            if original_area.is_finite() && original_area > 0.0 {
                return (projected_area_px2 / original_area).clamp(0.0, 1.0);
            }
        }
        if self.was_clipped {
            return AOA_PANE_CLIPPED_UNKNOWN_VISIBLE_FRACTION;
        }
        1.0
    }
}

fn empty_observation(
    pane: &AoaPaneRecord,
    viewport_px: [u32; 2],
    reason: AoaPaneObservationGateReason,
) -> AoaPaneFrameObservation {
    AoaPaneFrameObservation {
        pane_id: pane.pane_id.clone(),
        pane_ordinal: pane.pane_ordinal,
        viewport_px,
        screen_bbox_px: [0.0; 4],
        projected_area_px2: 0.0,
        min_projected_edge_px: 0.0,
        facing_dot: 0.0,
        visible_fraction: 0.0,
        occlusion_state: AoaPaneOcclusionState::Hidden,
        lod_class: AoaPaneLodClass::Culled,
        gate_reasons: vec![reason],
    }
}

fn project_pane_vertices(
    pane: &AoaPaneRecord,
    frame: AoaPaneObservationFrame,
) -> Result<ProjectedPane, AoaPaneObservationGateReason> {
    if frame.viewport_px[0] == 0 || frame.viewport_px[1] == 0 {
        return Err(AoaPaneObservationGateReason::NonFiniteProjection);
    }

    let mut clip_vertices = [ClipPaneVertex {
        clip: Vec4::ZERO,
        world: Vec3::ZERO,
    }; 3];
    let mut world_vertices = [Vec3::ZERO; 3];
    for (idx, vertex) in pane.model_vertices.iter().enumerate() {
        let model_vertex = Vec4::new(vertex[0], vertex[1], vertex[2], 1.0);
        let world = frame.model_matrix * model_vertex;
        let clip = frame.view_projection_matrix * world;
        let world = world.truncate();
        if !finite4(clip) || !finite3(world) {
            return Err(AoaPaneObservationGateReason::NonFiniteProjection);
        }
        clip_vertices[idx] = ClipPaneVertex { clip, world };
        world_vertices[idx] = world;
    }

    let original_screen_vertices = original_screen_vertices(clip_vertices, frame.viewport_px)?;
    let original_projected_area_px2 =
        original_screen_vertices.map(|vertices| polygon_area_px2(&vertices));
    let mut clipped = clip_vertices.to_vec();
    let original_len = clipped.len();
    clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.w - AOA_CLIP_W_EPSILON);
    if clipped.is_empty() {
        return Err(AoaPaneObservationGateReason::BehindCamera);
    }
    clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.x + vertex.clip.w);
    clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.w - vertex.clip.x);
    clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.y + vertex.clip.w);
    clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.w - vertex.clip.y);
    // glam::Mat4::perspective_rh uses the wgpu/D3D/Vulkan NDC depth range [0, 1].
    clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.z);
    clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.w - vertex.clip.z);

    if clipped.len() < 3 {
        return Err(AoaPaneObservationGateReason::Offscreen);
    }
    let screen_vertices = clipped
        .iter()
        .map(|vertex| clip_vertex_to_screen(*vertex, frame.viewport_px))
        .collect::<Result<Vec<_>, _>>()?;
    if polygon_area_px2(&screen_vertices) <= 0.0 {
        return Err(AoaPaneObservationGateReason::Offscreen);
    }

    Ok(ProjectedPane {
        screen_vertices,
        world_vertices,
        original_projected_area_px2,
        was_clipped: clipped.len() != original_len
            || clipped.iter().zip(clip_vertices.iter()).any(|(a, b)| {
                (a.clip - b.clip).length_squared() > 0.000_001
                    || (a.world - b.world).length_squared() > 0.000_001
            }),
    })
}

fn original_screen_vertices(
    vertices: [ClipPaneVertex; 3],
    viewport_px: [u32; 2],
) -> Result<Option<Vec<Vec2>>, AoaPaneObservationGateReason> {
    let mut projected = Vec::with_capacity(3);
    for vertex in vertices {
        if vertex.clip.w <= AOA_CLIP_W_EPSILON {
            return Ok(None);
        }
        projected.push(clip_vertex_to_screen(vertex, viewport_px)?);
    }
    Ok(Some(projected))
}

fn clip_vertex_to_screen(
    vertex: ClipPaneVertex,
    viewport_px: [u32; 2],
) -> Result<Vec2, AoaPaneObservationGateReason> {
    if vertex.clip.w <= AOA_CLIP_W_EPSILON {
        return Err(AoaPaneObservationGateReason::BehindCamera);
    }
    let ndc = vertex.clip.truncate() / vertex.clip.w;
    if !finite3(ndc) {
        return Err(AoaPaneObservationGateReason::NonFiniteProjection);
    }
    let width = viewport_px[0] as f32;
    let height = viewport_px[1] as f32;
    Ok(Vec2::new(
        (ndc.x * 0.5 + 0.5) * width,
        (1.0 - (ndc.y * 0.5 + 0.5)) * height,
    ))
}

fn clip_polygon_against_plane<F>(
    vertices: &[ClipPaneVertex],
    distance_to_inside: F,
) -> Vec<ClipPaneVertex>
where
    F: Fn(ClipPaneVertex) -> f32,
{
    if vertices.is_empty() {
        return Vec::new();
    }
    let mut output = Vec::with_capacity(vertices.len() + 1);
    let mut previous = *vertices.last().expect("non-empty checked above");
    let mut previous_distance = distance_to_inside(previous);
    let mut previous_inside = previous_distance >= 0.0;

    for current in vertices.iter().copied() {
        let current_distance = distance_to_inside(current);
        let current_inside = current_distance >= 0.0;
        if current_inside != previous_inside {
            output.push(intersect_clip_edge(
                previous,
                current,
                previous_distance,
                current_distance,
            ));
        }
        if current_inside {
            output.push(current);
        }
        previous = current;
        previous_distance = current_distance;
        previous_inside = current_inside;
    }
    output
}

fn intersect_clip_edge(
    from: ClipPaneVertex,
    to: ClipPaneVertex,
    from_distance: f32,
    to_distance: f32,
) -> ClipPaneVertex {
    let denominator = from_distance - to_distance;
    let t = if denominator.abs() <= f32::EPSILON {
        0.0
    } else {
        (from_distance / denominator).clamp(0.0, 1.0)
    };
    ClipPaneVertex {
        clip: from.clip + (to.clip - from.clip) * t,
        world: from.world + (to.world - from.world) * t,
    }
}

fn finite4(value: Vec4) -> bool {
    value
        .to_array()
        .iter()
        .all(|component| component.is_finite())
}

fn finite3(value: Vec3) -> bool {
    value
        .to_array()
        .iter()
        .all(|component| component.is_finite())
}

fn screen_bbox(vertices: &[Vec2]) -> [f32; 4] {
    let min_x = vertices
        .iter()
        .map(|vertex| vertex.x)
        .fold(f32::INFINITY, f32::min);
    let min_y = vertices
        .iter()
        .map(|vertex| vertex.y)
        .fold(f32::INFINITY, f32::min);
    let max_x = vertices
        .iter()
        .map(|vertex| vertex.x)
        .fold(f32::NEG_INFINITY, f32::max);
    let max_y = vertices
        .iter()
        .map(|vertex| vertex.y)
        .fold(f32::NEG_INFINITY, f32::max);
    [min_x, min_y, max_x, max_y]
}

fn polygon_area_px2(vertices: &[Vec2]) -> f32 {
    if vertices.len() < 3 {
        return 0.0;
    }
    vertices
        .iter()
        .zip(vertices.iter().cycle().skip(1))
        .take(vertices.len())
        .map(|(a, b)| a.x * b.y - b.x * a.y)
        .sum::<f32>()
        .abs()
        * 0.5
}

fn min_edge_px(vertices: &[Vec2]) -> f32 {
    if vertices.len() < 2 {
        return 0.0;
    }
    vertices
        .iter()
        .zip(vertices.iter().cycle().skip(1))
        .take(vertices.len())
        .map(|(a, b)| a.distance(*b))
        .fold(f32::INFINITY, f32::min)
}

fn facing_dot(camera_eye: Vec3, world_vertices: [Vec3; 3]) -> f32 {
    let a = world_vertices[0];
    let b = world_vertices[1];
    let c = world_vertices[2];
    let normal = (b - a).cross(c - a).normalize_or_zero();
    let centroid = (a + b + c) / 3.0;
    let to_camera = (camera_eye - centroid).normalize_or_zero();
    normal.dot(to_camera).clamp(-1.0, 1.0)
}

fn observation_gate_reasons(
    metrics: AoaPaneObservationMetrics,
) -> Vec<AoaPaneObservationGateReason> {
    let mut reasons = Vec::new();
    if !metrics_are_finite(metrics) {
        reasons.push(AoaPaneObservationGateReason::NonFiniteProjection);
        return reasons;
    }
    if metrics.visible_fraction <= 0.0 {
        reasons.push(AoaPaneObservationGateReason::Offscreen);
    }
    if metrics.facing_dot < AOA_PANE_MIN_FRONT_FACING_DOT {
        reasons.push(AoaPaneObservationGateReason::BackFacing);
    }
    if metrics.min_projected_edge_px < AOA_PANE_MIN_VISIBLE_EDGE_PX {
        reasons.push(AoaPaneObservationGateReason::Tiny);
    }
    reasons
}

fn metrics_are_finite(metrics: AoaPaneObservationMetrics) -> bool {
    metrics.projected_area_px2.is_finite()
        && metrics.min_projected_edge_px.is_finite()
        && metrics.facing_dot.is_finite()
        && metrics.visible_fraction.is_finite()
}

fn metrics_support_lod(
    metrics: AoaPaneObservationMetrics,
    lod: AoaPaneLodClass,
    scale: f32,
) -> bool {
    let scale = scale.clamp(0.0, 1.0);
    match lod {
        AoaPaneLodClass::Text => {
            metrics.projected_area_px2 >= AOA_PANE_TEXT_AREA_PX2 * scale
                && metrics.min_projected_edge_px >= AOA_PANE_TEXT_MIN_EDGE_PX * scale
                && metrics.facing_dot >= AOA_PANE_TEXT_MIN_FACING_DOT * scale
                && metrics.visible_fraction >= AOA_PANE_TEXT_MIN_VISIBLE_FRACTION * scale
        }
        AoaPaneLodClass::CompactData => {
            metrics.projected_area_px2 >= AOA_PANE_COMPACT_AREA_PX2 * scale
                && metrics.min_projected_edge_px >= AOA_PANE_COMPACT_MIN_EDGE_PX * scale
                && metrics.facing_dot >= AOA_PANE_COMPACT_MIN_FACING_DOT * scale
                && metrics.visible_fraction >= AOA_PANE_COMPACT_MIN_VISIBLE_FRACTION * scale
        }
        AoaPaneLodClass::Glyph => {
            metrics.projected_area_px2 >= AOA_PANE_GLYPH_AREA_PX2 * scale
                && metrics.min_projected_edge_px >= AOA_PANE_GLYPH_MIN_EDGE_PX * scale
                && metrics.visible_fraction >= AOA_PANE_GLYPH_MIN_VISIBLE_FRACTION * scale
        }
        AoaPaneLodClass::Accent => {
            metrics.projected_area_px2 >= AOA_PANE_ACCENT_AREA_PX2 * scale
                && metrics.min_projected_edge_px >= AOA_PANE_ACCENT_MIN_EDGE_PX * scale
        }
        AoaPaneLodClass::EdgeOnly => {
            metrics.visible_fraction > 0.0
                && metrics.min_projected_edge_px >= AOA_PANE_MIN_VISIBLE_EDGE_PX * scale
        }
        AoaPaneLodClass::Culled => true,
    }
}

fn lod_metric_ratio(metrics: AoaPaneObservationMetrics, lod: AoaPaneLodClass) -> f32 {
    if !metrics_are_finite(metrics) {
        return 0.0;
    }
    match lod {
        AoaPaneLodClass::Text => [
            metrics.projected_area_px2 / AOA_PANE_TEXT_AREA_PX2,
            metrics.min_projected_edge_px / AOA_PANE_TEXT_MIN_EDGE_PX,
            metrics.facing_dot / AOA_PANE_TEXT_MIN_FACING_DOT,
            metrics.visible_fraction / AOA_PANE_TEXT_MIN_VISIBLE_FRACTION,
        ],
        AoaPaneLodClass::CompactData => [
            metrics.projected_area_px2 / AOA_PANE_COMPACT_AREA_PX2,
            metrics.min_projected_edge_px / AOA_PANE_COMPACT_MIN_EDGE_PX,
            metrics.facing_dot / AOA_PANE_COMPACT_MIN_FACING_DOT,
            metrics.visible_fraction / AOA_PANE_COMPACT_MIN_VISIBLE_FRACTION,
        ],
        AoaPaneLodClass::Glyph => [
            metrics.projected_area_px2 / AOA_PANE_GLYPH_AREA_PX2,
            metrics.min_projected_edge_px / AOA_PANE_GLYPH_MIN_EDGE_PX,
            f32::INFINITY,
            metrics.visible_fraction / AOA_PANE_GLYPH_MIN_VISIBLE_FRACTION,
        ],
        AoaPaneLodClass::Accent => [
            metrics.projected_area_px2 / AOA_PANE_ACCENT_AREA_PX2,
            metrics.min_projected_edge_px / AOA_PANE_ACCENT_MIN_EDGE_PX,
            f32::INFINITY,
            f32::INFINITY,
        ],
        AoaPaneLodClass::EdgeOnly => [
            f32::INFINITY,
            metrics.min_projected_edge_px / AOA_PANE_MIN_VISIBLE_EDGE_PX,
            f32::INFINITY,
            metrics.visible_fraction.max(0.0),
        ],
        AoaPaneLodClass::Culled => [0.0; 4],
    }
    .into_iter()
    .filter(|ratio| ratio.is_finite())
    .fold(f32::INFINITY, f32::min)
}

fn smoothstep(edge0: f32, edge1: f32, value: f32) -> f32 {
    if !value.is_finite() || edge0 >= edge1 {
        return 0.0;
    }
    let t = ((value - edge0) / (edge1 - edge0)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tetrix_count_formulas_match_active_shader_depth() {
        assert_eq!(AOA_GEOMETRY_REVISION, "aoa-regular-tetrix-v4-perfect-fit-oarb");
        assert_eq!(AOA_TETRIX_RENDER_DEPTH, 4);
        assert_eq!(AOA_LEAF_FACE_EDGE_UNITS, 48);
        assert_eq!(AOA_PARENT_EDGE_UNITS, 768);
        assert_eq!(AOA_OARB_INNER_VOID_RADIUS_FILL_RATIO, 1.0);
        assert_eq!(aoa_leaf_tetrahedron_count(0), 1);
        assert_eq!(aoa_leaf_tetrahedron_count(1), 4);
        assert_eq!(aoa_leaf_tetrahedron_count(2), 16);
        assert_eq!(aoa_leaf_tetrahedron_count(3), 64);
        assert_eq!(aoa_leaf_tetrahedron_count(4), 256);
        assert_eq!(aoa_total_tetrahedron_count(4), 341);
        assert_eq!(aoa_raw_edge_segment_count(4), 1536);
        assert_eq!(aoa_raw_triangular_pane_count(4), 1024);
    }

    #[test]
    fn root_model_vertices_form_regular_incentered_pyramid() {
        let center = Vec3::ZERO;
        let vertices = AOA_ROOT_MODEL_VERTICES.map(Vec3::from_array);
        let mut edges = Vec::new();
        for (a, b) in [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)] {
            edges.push(vertices[a].distance(vertices[b]));
        }
        for edge in edges {
            assert!((edge - AOA_ROOT_EDGE).abs() < 0.000_01);
        }
        assert!(vertices[0].y < center.y);
        assert!(vertices[1].y < center.y);
        assert!(vertices[2].y < center.y);
        assert!(vertices[3].y > center.y);
    }

    #[test]
    fn lineage_and_ordinal_formula_match_shader_order() {
        let lineage = vec![AoaChild::A, AoaChild::D];
        assert_eq!(aoa_tetra_index(&lineage), 3);
        assert_eq!(aoa_pane_start_ordinal(2), 0);
        assert_eq!(aoa_pane_ordinal(&lineage, AoaFaceKey::Bcd), 13);
        assert_eq!(
            aoa_pane_id(&lineage, AoaFaceKey::Bcd),
            "aoa:pane:v1:a.d:bcd"
        );
        assert_eq!(aoa_lineage_from_tetra_index(2, 3), lineage);
    }

    #[test]
    fn active_manifest_has_all_depth_four_leaf_panes_with_unique_identity() {
        let manifest = aoa_active_pane_manifest();
        assert_eq!(manifest.render_depth, AOA_TETRIX_RENDER_DEPTH);
        assert_eq!(manifest.pane_count, 1024);
        assert_eq!(manifest.panes.len(), 1024);
        assert!(manifest.panes.iter().all(|pane| pane.depth == AOA_TETRIX_RENDER_DEPTH));
        assert!(aoa_manifest_has_unique_identity(&manifest));
    }

    fn default_observation_frame(model_matrix: Mat4) -> AoaPaneObservationFrame {
        let camera_eye = Vec3::new(0.0, 0.0, 2.0);
        let view = Mat4::look_at_rh(camera_eye, Vec3::new(0.0, 0.0, -4.0), Vec3::Y);
        let projection = Mat4::perspective_rh(60.0f32.to_radians(), 16.0 / 9.0, 0.1, 50.0);
        AoaPaneObservationFrame::new(model_matrix, view, projection, camera_eye, 1920, 1080)
    }

    fn root_pane(face_key: AoaFaceKey) -> AoaPaneRecord {
        aoa_pane_record(&[], face_key)
    }

    fn clip_for_test(vertices: Vec<ClipPaneVertex>) -> Vec<ClipPaneVertex> {
        let mut clipped =
            clip_polygon_against_plane(&vertices, |vertex| vertex.clip.w - AOA_CLIP_W_EPSILON);
        clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.x + vertex.clip.w);
        clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.w - vertex.clip.x);
        clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.y + vertex.clip.w);
        clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.w - vertex.clip.y);
        clipped = clip_polygon_against_plane(&clipped, |vertex| vertex.clip.z);
        clip_polygon_against_plane(&clipped, |vertex| vertex.clip.w - vertex.clip.z)
    }

    #[test]
    fn pane_observation_records_visible_root_pane_metrics() {
        let frame = default_observation_frame(
            Mat4::from_translation(Vec3::new(0.0, -0.08, -1.85))
                * Mat4::from_scale(Vec3::splat(2.0)),
        );
        let observation = aoa_observe_pane(&root_pane(AoaFaceKey::Abd), frame);

        assert_eq!(observation.pane_id, "aoa:pane:v1:r:abd");
        assert_eq!(observation.viewport_px, [1920, 1080]);
        assert!(observation.projected_area_px2 > 0.0);
        assert!(observation.min_projected_edge_px > AOA_PANE_MIN_VISIBLE_EDGE_PX);
        assert!(observation.facing_dot >= AOA_PANE_MIN_FRONT_FACING_DOT);
        assert!(observation.visible_fraction > 0.0);
        assert_ne!(observation.lod_class, AoaPaneLodClass::Culled);
        assert!(observation.gate_reasons.is_empty());
    }

    #[test]
    fn pane_observation_covers_back_facing_tiny_and_offscreen_cases() {
        let base_model = Mat4::from_translation(Vec3::new(0.0, -0.08, -1.85))
            * Mat4::from_scale(Vec3::splat(2.0));
        let frame = default_observation_frame(base_model);
        let back_facing = aoa_observe_pane(&root_pane(AoaFaceKey::Bcd), frame);
        assert_eq!(back_facing.lod_class, AoaPaneLodClass::Culled);
        assert!(back_facing
            .gate_reasons
            .contains(&AoaPaneObservationGateReason::BackFacing));

        let tiny_frame = default_observation_frame(
            Mat4::from_translation(Vec3::new(0.0, -0.08, -1.85))
                * Mat4::from_scale(Vec3::splat(0.002)),
        );
        let tiny = aoa_observe_pane(&root_pane(AoaFaceKey::Abd), tiny_frame);
        assert_eq!(tiny.lod_class, AoaPaneLodClass::Culled);
        assert!(tiny
            .gate_reasons
            .contains(&AoaPaneObservationGateReason::Tiny));

        let offscreen_frame = default_observation_frame(
            Mat4::from_translation(Vec3::new(100.0, -0.08, -1.85))
                * Mat4::from_scale(Vec3::splat(2.0)),
        );
        let offscreen = aoa_observe_pane(&root_pane(AoaFaceKey::Abd), offscreen_frame);
        assert_eq!(offscreen.lod_class, AoaPaneLodClass::Culled);
        assert!(offscreen
            .gate_reasons
            .contains(&AoaPaneObservationGateReason::Offscreen));
    }

    #[test]
    fn pane_observation_culls_geometry_outside_depth_range() {
        let far_frame = default_observation_frame(
            Mat4::from_translation(Vec3::new(0.0, -0.08, -100.0))
                * Mat4::from_scale(Vec3::splat(2.0)),
        );
        let far = aoa_observe_pane(&root_pane(AoaFaceKey::Abd), far_frame);
        assert_eq!(far.lod_class, AoaPaneLodClass::Culled);
        assert_eq!(far.visible_fraction, 0.0);
        assert!(far
            .gate_reasons
            .contains(&AoaPaneObservationGateReason::Offscreen));
    }

    #[test]
    fn view_volume_clip_uses_triangle_geometry_not_bbox_overlap() {
        let outside_corner = vec![
            ClipPaneVertex {
                clip: Vec4::new(0.8, 1.2, 0.5, 1.0),
                world: Vec3::ZERO,
            },
            ClipPaneVertex {
                clip: Vec4::new(1.2, 0.8, 0.5, 1.0),
                world: Vec3::ZERO,
            },
            ClipPaneVertex {
                clip: Vec4::new(1.2, 1.2, 0.5, 1.0),
                world: Vec3::ZERO,
            },
        ];
        let clipped = clip_for_test(outside_corner);
        let screen_vertices = clipped
            .iter()
            .map(|vertex| clip_vertex_to_screen(*vertex, [1920, 1080]))
            .collect::<Result<Vec<_>, _>>()
            .expect("clipped vertices should be projectable");

        assert!(
            polygon_area_px2(&screen_vertices) <= 0.001,
            "bbox-overlap alone must not make a pane observable"
        );
    }

    #[test]
    fn view_volume_clip_preserves_camera_crossing_triangles() {
        let camera_crossing = vec![
            ClipPaneVertex {
                clip: Vec4::new(-0.25, -0.25, 0.2, 1.0),
                world: Vec3::ZERO,
            },
            ClipPaneVertex {
                clip: Vec4::new(0.25, -0.25, 0.2, 1.0),
                world: Vec3::ZERO,
            },
            ClipPaneVertex {
                clip: Vec4::new(0.0, 0.35, 0.2, -0.5),
                world: Vec3::ZERO,
            },
        ];
        let clipped = clip_for_test(camera_crossing);

        let tolerance = 0.000_1;
        assert!(clipped.len() >= 3);
        assert!(clipped.iter().all(|vertex| {
            vertex.clip.w > 0.0
                && vertex.clip.z >= -tolerance
                && vertex.clip.z <= vertex.clip.w + tolerance
                && vertex.clip.x.abs() <= vertex.clip.w + tolerance
                && vertex.clip.y.abs() <= vertex.clip.w + tolerance
        }));
    }

    #[test]
    fn lod_thresholds_and_hysteresis_are_deterministic() {
        let text = AoaPaneObservationMetrics {
            projected_area_px2: AOA_PANE_TEXT_AREA_PX2,
            min_projected_edge_px: AOA_PANE_TEXT_MIN_EDGE_PX,
            facing_dot: AOA_PANE_TEXT_MIN_FACING_DOT,
            visible_fraction: AOA_PANE_TEXT_MIN_VISIBLE_FRACTION,
        };
        assert_eq!(aoa_raw_lod_class_for_metrics(text), AoaPaneLodClass::Text);

        let compact = AoaPaneObservationMetrics {
            projected_area_px2: AOA_PANE_COMPACT_AREA_PX2,
            min_projected_edge_px: AOA_PANE_COMPACT_MIN_EDGE_PX,
            facing_dot: AOA_PANE_COMPACT_MIN_FACING_DOT,
            visible_fraction: AOA_PANE_COMPACT_MIN_VISIBLE_FRACTION,
        };
        assert_eq!(
            aoa_raw_lod_class_for_metrics(compact),
            AoaPaneLodClass::CompactData
        );

        let glyph = AoaPaneObservationMetrics {
            projected_area_px2: AOA_PANE_GLYPH_AREA_PX2,
            min_projected_edge_px: AOA_PANE_GLYPH_MIN_EDGE_PX,
            facing_dot: AOA_PANE_MIN_FRONT_FACING_DOT,
            visible_fraction: AOA_PANE_GLYPH_MIN_VISIBLE_FRACTION,
        };
        assert_eq!(aoa_raw_lod_class_for_metrics(glyph), AoaPaneLodClass::Glyph);

        let accent = AoaPaneObservationMetrics {
            projected_area_px2: AOA_PANE_ACCENT_AREA_PX2,
            min_projected_edge_px: AOA_PANE_ACCENT_MIN_EDGE_PX,
            facing_dot: AOA_PANE_MIN_FRONT_FACING_DOT,
            visible_fraction: 0.5,
        };
        assert_eq!(
            aoa_raw_lod_class_for_metrics(accent),
            AoaPaneLodClass::Accent
        );

        let edge_only = AoaPaneObservationMetrics {
            projected_area_px2: AOA_PANE_ACCENT_AREA_PX2 - 1.0,
            min_projected_edge_px: AOA_PANE_MIN_VISIBLE_EDGE_PX,
            facing_dot: AOA_PANE_MIN_FRONT_FACING_DOT,
            visible_fraction: 0.5,
        };
        assert_eq!(
            aoa_raw_lod_class_for_metrics(edge_only),
            AoaPaneLodClass::EdgeOnly
        );

        let culled = AoaPaneObservationMetrics {
            min_projected_edge_px: AOA_PANE_MIN_VISIBLE_EDGE_PX - 0.01,
            ..edge_only
        };
        assert_eq!(
            aoa_raw_lod_class_for_metrics(culled),
            AoaPaneLodClass::Culled
        );

        let mut reasons = Vec::new();
        assert_eq!(
            aoa_lod_class_for_metrics_with_state(
                edge_only,
                Some(AoaPaneLodClass::CompactData),
                AOA_PANE_LOD_MIN_DWELL_MS - 1,
                AoaPaneLodConfig::default(),
                &mut reasons,
            ),
            AoaPaneLodClass::CompactData
        );
        assert!(reasons.contains(&AoaPaneObservationGateReason::MinimumDwellHold));

        let mut reasons = Vec::new();
        let text_exit_band = AoaPaneObservationMetrics {
            projected_area_px2: AOA_PANE_TEXT_AREA_PX2 * 0.90,
            min_projected_edge_px: AOA_PANE_TEXT_MIN_EDGE_PX * 0.90,
            facing_dot: AOA_PANE_TEXT_MIN_FACING_DOT * 0.90,
            visible_fraction: AOA_PANE_TEXT_MIN_VISIBLE_FRACTION * 0.90,
        };
        assert_eq!(
            aoa_lod_class_for_metrics_with_state(
                text_exit_band,
                Some(AoaPaneLodClass::Text),
                AOA_PANE_LOD_MIN_DWELL_MS,
                AoaPaneLodConfig::default(),
                &mut reasons,
            ),
            AoaPaneLodClass::Text
        );
        assert!(reasons.contains(&AoaPaneObservationGateReason::HysteresisHold));
    }

    #[test]
    fn binding_modes_have_monotonic_lod_requirements_and_fade_alpha() {
        assert_eq!(
            aoa_min_lod_for_binding_mode(AoaPaneBindingMode::EdgeAccent),
            AoaPaneLodClass::Accent
        );
        assert_eq!(
            aoa_min_lod_for_binding_mode(AoaPaneBindingMode::SignalGlyph),
            AoaPaneLodClass::Glyph
        );
        assert_eq!(
            aoa_min_lod_for_binding_mode(AoaPaneBindingMode::DataGlyph),
            AoaPaneLodClass::CompactData
        );
        assert_eq!(
            aoa_min_lod_for_binding_mode(AoaPaneBindingMode::TriTextureMasked),
            AoaPaneLodClass::Text
        );

        let mut observation = AoaPaneFrameObservation {
            pane_id: "aoa:pane:v1:a:bcd".to_string(),
            pane_ordinal: 5,
            viewport_px: [1920, 1080],
            screen_bbox_px: [0.0, 0.0, 100.0, 100.0],
            projected_area_px2: AOA_PANE_ACCENT_AREA_PX2,
            min_projected_edge_px: AOA_PANE_ACCENT_MIN_EDGE_PX,
            facing_dot: AOA_PANE_MIN_FRONT_FACING_DOT,
            visible_fraction: 0.5,
            occlusion_state: AoaPaneOcclusionState::Visible,
            lod_class: AoaPaneLodClass::Accent,
            gate_reasons: Vec::new(),
        };

        assert!(aoa_pane_lod_supports_binding_mode(
            observation.lod_class,
            AoaPaneBindingMode::EdgeAccent
        ));
        assert!(!aoa_pane_lod_supports_binding_mode(
            observation.lod_class,
            AoaPaneBindingMode::SignalGlyph
        ));
        assert_eq!(
            aoa_pane_lod_alpha_for_binding_mode(&observation, AoaPaneBindingMode::SignalGlyph),
            0.0
        );

        let threshold_alpha =
            aoa_pane_lod_alpha_for_binding_mode(&observation, AoaPaneBindingMode::EdgeAccent);
        observation.projected_area_px2 = AOA_PANE_ACCENT_AREA_PX2 * 1.2;
        observation.min_projected_edge_px = AOA_PANE_ACCENT_MIN_EDGE_PX * 1.2;
        let settled_alpha =
            aoa_pane_lod_alpha_for_binding_mode(&observation, AoaPaneBindingMode::EdgeAccent);
        assert!(
            settled_alpha > threshold_alpha,
            "alpha should ramp smoothly above the LOD threshold"
        );
        assert!(settled_alpha > 0.95);
    }

    #[test]
    fn root_records_have_expected_ids_and_shader_corner_order() {
        let manifest = aoa_pane_manifest(0);
        assert_eq!(manifest.panes.len(), 4);

        let abd = &manifest.panes[0];
        assert_eq!(abd.pane_id, "aoa:pane:v1:r:abd");
        assert_eq!(abd.pane_ordinal, 0);
        assert_eq!(abd.depth, 0);
        assert_eq!(abd.lineage_path, Vec::<AoaChild>::new());
        assert_eq!(abd.corner_order, vec!["a", "b", "d"]);
        assert_eq!(
            abd.model_vertices,
            [
                AOA_ROOT_MODEL_VERTICES[0],
                AOA_ROOT_MODEL_VERTICES[1],
                AOA_ROOT_MODEL_VERTICES[3]
            ]
        );
        assert_eq!(abd.boundary_role, AoaBoundaryRole::RootHull);

        let acb = &manifest.panes[3];
        assert_eq!(acb.pane_id, "aoa:pane:v1:r:acb");
        assert_eq!(acb.corner_order, vec!["a", "c", "b"]);
        assert_eq!(
            acb.model_vertices,
            [
                AOA_ROOT_MODEL_VERTICES[0],
                AOA_ROOT_MODEL_VERTICES[2],
                AOA_ROOT_MODEL_VERTICES[1]
            ]
        );
    }

    #[test]
    fn descendant_record_carries_lineage_parent_and_ancestors() {
        let records = aoa_pane_records(2);
        let pane = records
            .iter()
            .find(|pane| pane.pane_id == "aoa:pane:v1:a.d:bcd")
            .expect("depth-2 pane should exist");

        assert_eq!(pane.pane_ordinal, 13);
        assert_eq!(pane.depth, 2);
        assert_eq!(pane.lineage_digits, vec![0, 3]);
        assert_eq!(pane.tetra_id, "aoa:tetra:v1:a.d");
        assert_eq!(pane.parent_tetra_id.as_deref(), Some("aoa:tetra:v1:a"));
        assert_eq!(
            pane.ancestor_pane_ids,
            vec!["aoa:pane:v1:r:bcd", "aoa:pane:v1:a:bcd"]
        );
        assert_eq!(pane.face_key, AoaFaceKey::Bcd);
        assert_eq!(pane.face_index, 1);
    }

    #[test]
    fn boundary_role_distinguishes_root_hull_subfaces_from_void_walls() {
        let records = aoa_pane_records(1);
        let hull_subface = records
            .iter()
            .find(|pane| pane.pane_id == "aoa:pane:v1:a:abd")
            .expect("child subface should exist");
        let void_wall = records
            .iter()
            .find(|pane| pane.pane_id == "aoa:pane:v1:a:bcd")
            .expect("child void wall should exist");

        assert_eq!(hull_subface.boundary_role, AoaBoundaryRole::HullSubface);
        assert_eq!(void_wall.boundary_role, AoaBoundaryRole::VoidWall);
    }

    #[test]
    fn triangular_uv_matches_shader_barycentric_mapping() {
        let apex = aoa_triangular_uv_from_barycentric([1.0, 0.0, 0.0]);
        let right = aoa_triangular_uv_from_barycentric([0.0, 1.0, 0.0]);
        let top = aoa_triangular_uv_from_barycentric([0.0, 0.0, 1.0]);

        assert_eq!(apex, [0.0, 0.0]);
        assert_eq!(right, [1.0, 0.0]);
        assert!((top[0] - 0.5).abs() < 1e-6);
        assert!(top[1] > 0.866 && top[1] < 0.867);
    }

    #[test]
    fn high_contrast_pane_payload_clips_to_triangle_bounds() {
        for inside in [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.2, 0.3, 0.5],
            [-0.0005, 0.50025, 0.50025],
        ] {
            assert!(aoa_barycentric_inside_triangle(
                inside,
                AOA_PANE_CLIP_TOLERANCE
            ));
            assert_eq!(
                aoa_pane_payload_alpha(1.0, inside, AOA_PANE_CLIP_TOLERANCE),
                1.0
            );
        }

        for outside in [
            [-0.01, 0.50, 0.51],
            [0.50, -0.01, 0.51],
            [0.50, 0.51, -0.01],
            [0.25, 0.25, 0.25],
            [f32::NAN, 0.5, 0.5],
        ] {
            assert!(!aoa_barycentric_inside_triangle(
                outside,
                AOA_PANE_CLIP_TOLERANCE
            ));
            assert!(
                aoa_pane_payload_alpha(1.0, outside, AOA_PANE_CLIP_TOLERANCE)
                    <= AOA_PANE_CLIP_TOLERANCE,
                "outside samples must not leak a high-contrast pane card"
            );
        }

        assert_eq!(
            aoa_pane_payload_alpha(f32::NAN, [0.2, 0.3, 0.5], AOA_PANE_CLIP_TOLERANCE),
            0.0
        );
    }

    #[test]
    fn pane_payload_requires_binding_transform_and_mask() {
        let mut gate = AoaPanePayloadGate::visible_inside([0.2, 0.3, 0.5]);

        gate.has_valid_pane_binding = false;
        assert_eq!(
            aoa_pane_payload_block_reason(gate),
            Some(AoaPanePayloadBlockReason::MissingPaneBinding)
        );

        gate = AoaPanePayloadGate::visible_inside([0.2, 0.3, 0.5]);
        gate.has_pane_transform = false;
        assert_eq!(
            aoa_pane_payload_block_reason(gate),
            Some(AoaPanePayloadBlockReason::MissingPaneTransform)
        );

        gate = AoaPanePayloadGate::visible_inside([0.2, 0.3, 0.5]);
        gate.has_barycentric_mask = false;
        assert_eq!(
            aoa_pane_payload_block_reason(gate),
            Some(AoaPanePayloadBlockReason::MissingBarycentricMask)
        );
    }

    #[test]
    fn pane_payload_fails_closed_when_not_geometrically_observable() {
        let mut gate = AoaPanePayloadGate::visible_inside([0.2, 0.3, 0.5]);

        gate.pane_visible = false;
        assert_eq!(
            aoa_pane_payload_block_reason(gate),
            Some(AoaPanePayloadBlockReason::PaneHidden)
        );
        assert_eq!(aoa_pane_payload_alpha_after_gate(1.0, gate), 0.0);

        gate = AoaPanePayloadGate::visible_inside([0.2, 0.3, 0.5]);
        gate.facing_dot = -0.1;
        assert_eq!(
            aoa_pane_payload_block_reason(gate),
            Some(AoaPanePayloadBlockReason::BackFacing)
        );
        assert_eq!(aoa_pane_payload_alpha_after_gate(1.0, gate), 0.0);

        gate = AoaPanePayloadGate::visible_inside([0.2, 0.3, 0.5]);
        gate.facing_dot = f32::NAN;
        assert_eq!(
            aoa_pane_payload_block_reason(gate),
            Some(AoaPanePayloadBlockReason::BackFacing)
        );
        assert_eq!(aoa_pane_payload_alpha_after_gate(1.0, gate), 0.0);

        gate = AoaPanePayloadGate::visible_inside([0.2, 0.3, 0.5]);
        gate.min_projected_edge_px = AOA_PANE_MIN_VISIBLE_EDGE_PX - 0.1;
        assert_eq!(
            aoa_pane_payload_block_reason(gate),
            Some(AoaPanePayloadBlockReason::BelowVisibilityThreshold)
        );
        assert_eq!(aoa_pane_payload_alpha_after_gate(1.0, gate), 0.0);

        gate = AoaPanePayloadGate::visible_inside([0.2, 0.3, 0.5]);
        gate.min_projected_edge_px = f32::INFINITY;
        assert_eq!(
            aoa_pane_payload_block_reason(gate),
            Some(AoaPanePayloadBlockReason::BelowVisibilityThreshold)
        );
        assert_eq!(aoa_pane_payload_alpha_after_gate(1.0, gate), 0.0);

        gate = AoaPanePayloadGate::visible_inside([0.2, 0.3, 0.5]);
        assert_eq!(aoa_pane_payload_alpha_after_gate(f32::NAN, gate), 0.0);

        gate = AoaPanePayloadGate::visible_inside([-0.01, 0.50, 0.51]);
        assert_eq!(
            aoa_pane_payload_block_reason(gate),
            Some(AoaPanePayloadBlockReason::OutsideTriangle)
        );
        assert_eq!(aoa_pane_payload_alpha_after_gate(1.0, gate), 0.0);
    }

    #[test]
    fn manifest_records_are_json_serializable() {
        let manifest = aoa_pane_manifest(1);
        let json = serde_json::to_string(&manifest).expect("manifest should serialize");
        assert!(json.contains("aoa:pane:v1:a:abd"));
        assert!(json.contains("aoa-regular-tetrix-v4-perfect-fit-oarb"));
        assert!(json.contains("aperture-of-apertures"));
    }
}
