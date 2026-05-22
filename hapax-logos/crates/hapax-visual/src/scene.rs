//! 3D scene graph for the compositor migration.
//!
//! Phase 0 introduced a static proof scene. Phase 1 replaces it with a
//! dynamic scene graph that reads from `ContentSourceManager` and maps
//! each active content source to a positioned 3D quad.

use glam::{Mat4, Vec3};
use std::collections::HashMap;

use crate::content_sources::{
    ActiveContentSourceInfo, AoaPaneBindingRejectionReason, AoaPaneStreamPosture,
    AoaValidatedPaneBinding,
};

pub use crate::aoa_panes::{
    aoa_active_pane_manifest, aoa_leaf_tetrahedron_count, aoa_min_lod_for_binding_mode,
    aoa_observe_panes, aoa_pane_lod_alpha_for_binding_mode, aoa_pane_lod_supports_binding_mode,
    aoa_raw_edge_segment_count, aoa_raw_triangular_pane_count, aoa_total_tetrahedron_count,
    AoaPaneBindingMode, AoaPaneFrameObservation, AoaPaneLodClass, AoaPaneObservationFrame,
    AoaPaneRecord, AOA_TETRIX_RENDER_DEPTH,
};

// ─── Z-plane constants ────────────────────────────────────────────
// Must stay synchronised with agents/studio_compositor/z_plane_constants.py.
// The Python floats (0.2, 0.5, 0.9, 1.0) are abstract layers; the real
// Z values here place quads in world space where the perspective camera
// makes the depth relationships visually obvious.

/// Real-Z position for each scrim layer.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ZPlane {
    /// z_order 1-2 → behind everything, atmospheric backdrop
    BeyondScrim,
    /// z_order 3-4 → mid-depth, secondary elements
    MidScrim,
    /// z_order 5-7 → primary visual plane
    OnScrim,
    /// z_order 8-10 → closest to camera, hero content
    SurfaceScrim,
}

impl ZPlane {
    /// Map a manifest `z_order` integer to a ZPlane.
    pub fn from_z_order(z_order: i32) -> Self {
        match z_order {
            0..=2 => ZPlane::BeyondScrim,
            3..=4 => ZPlane::MidScrim,
            5..=7 => ZPlane::OnScrim,
            _ => ZPlane::SurfaceScrim,
        }
    }

    /// Real-world Z coordinate for this plane.
    pub fn z_position(&self) -> f32 {
        match self {
            ZPlane::BeyondScrim => -8.0,
            ZPlane::MidScrim => -5.0,
            ZPlane::OnScrim => -3.0,
            ZPlane::SurfaceScrim => -2.0,
        }
    }

    /// Python-side abstract float value for parity tests.
    pub fn python_float(&self) -> f32 {
        match self {
            ZPlane::BeyondScrim => 0.2,
            ZPlane::MidScrim => 0.5,
            ZPlane::OnScrim => 0.9,
            ZPlane::SurfaceScrim => 1.0,
        }
    }
}

// ─── Scene node ────────────────────────────────────────────────────

pub const AOA_NODE_LABEL: &str = "aperture-of-apertures";
pub const AOA_COMPAT_SOURCE_IDS: &[&str] = &[
    "aoa",
    "aperture-of-apertures",
    "aoa-pyramid",
    // Legacy source IDs. These remain as compatibility aliases only; the
    // authored AoA anchor supplies its own geometry and never samples them.
    "sierpinski",
    "sierpinski-lines",
];
pub const AOA_BASE_GRID_UNITS: f32 = 2.0;
const NEBULOUS_SCROOM_CAMERA_SIDE_DEPTH_FACTOR: f32 = 0.39;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AnchorRole {
    High,
    Medium,
    Low,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TetrahedralQuadrant {
    A,
    B,
    C,
    D,
}

pub struct SceneAnchor {
    pub world_pos: Vec3,
    pub role: AnchorRole,
    pub quadrant: TetrahedralQuadrant,
}

const AOA_CENTROID: Vec3 = Vec3::new(0.0, -0.30, -2.06);
const UTAMA_RADIUS: f32 = 2.5;
const MADYA_RADIUS_MIN: f32 = 2.5;
const MADYA_RADIUS_MAX: f32 = 4.5;
const NISTA_RADIUS_MIN: f32 = 4.5;

fn scale_anchor_outward(local: Vec3, role: AnchorRole) -> Vec3 {
    let dir = local - AOA_CENTROID;
    let dist = dir.length();
    if dist < 0.001 {
        return local;
    }
    let target_min = match role {
        AnchorRole::High => MADYA_RADIUS_MIN + 0.5,
        AnchorRole::Medium => NISTA_RADIUS_MIN + 0.3,
        AnchorRole::Low => NISTA_RADIUS_MIN + 1.5,
    };
    if dist >= target_min {
        return local;
    }
    AOA_CENTROID + dir.normalize() * target_min
}

pub fn scene_anchors() -> Vec<SceneAnchor> {
    use AnchorRole::*;
    use TetrahedralQuadrant::*;
    vec![
        // 8 cube-vertices (HIGH entropy — cameras, YouTube, live video)
        SceneAnchor { world_pos: Vec3::new(-1.160, -1.180, -1.380), role: High, quadrant: A },
        SceneAnchor { world_pos: Vec3::new( 1.160, -1.180, -1.380), role: High, quadrant: B },
        SceneAnchor { world_pos: Vec3::new( 0.000,  0.900, -1.380), role: High, quadrant: C },
        SceneAnchor { world_pos: Vec3::new( 0.000, -0.490, -3.300), role: High, quadrant: D },
        SceneAnchor { world_pos: Vec3::new( 1.160,  0.205, -2.340), role: High, quadrant: D },
        SceneAnchor { world_pos: Vec3::new(-1.160,  0.205, -2.340), role: High, quadrant: C },
        SceneAnchor { world_pos: Vec3::new( 0.000, -1.875, -2.340), role: High, quadrant: B },
        SceneAnchor { world_pos: Vec3::new( 0.000, -0.485, -0.420), role: High, quadrant: A },
        // 6 octahedron-vertices (MEDIUM entropy — wards, data, tickers)
        SceneAnchor { world_pos: Vec3::new( 0.000, -1.180, -1.380), role: Medium, quadrant: A },
        SceneAnchor { world_pos: Vec3::new(-0.580, -0.140, -1.380), role: Medium, quadrant: A },
        SceneAnchor { world_pos: Vec3::new(-0.580, -0.835, -2.340), role: Medium, quadrant: D },
        SceneAnchor { world_pos: Vec3::new( 0.580, -0.140, -1.380), role: Medium, quadrant: B },
        SceneAnchor { world_pos: Vec3::new( 0.580, -0.835, -2.340), role: Medium, quadrant: B },
        SceneAnchor { world_pos: Vec3::new( 0.000,  0.205, -2.340), role: Medium, quadrant: C },
        // 4 child centroids (MEDIUM — semantic cluster centers)
        SceneAnchor { world_pos: Vec3::new(-0.580, -0.834, -1.620), role: Medium, quadrant: A },
        SceneAnchor { world_pos: Vec3::new( 0.580, -0.834, -1.620), role: Medium, quadrant: B },
        SceneAnchor { world_pos: Vec3::new( 0.000,  0.206, -1.620), role: Medium, quadrant: C },
        SceneAnchor { world_pos: Vec3::new( 0.000, -0.489, -2.580), role: Medium, quadrant: D },
        // 12 trisection points (LOW entropy — accent, atmospheric, signals)
        SceneAnchor { world_pos: Vec3::new(-0.387, -1.180, -1.380), role: Low, quadrant: A },
        SceneAnchor { world_pos: Vec3::new( 0.387, -1.180, -1.380), role: Low, quadrant: B },
        SceneAnchor { world_pos: Vec3::new(-0.773, -0.487, -1.380), role: Low, quadrant: A },
        SceneAnchor { world_pos: Vec3::new(-0.387,  0.207, -1.380), role: Low, quadrant: C },
        SceneAnchor { world_pos: Vec3::new(-0.773, -0.950, -2.020), role: Low, quadrant: A },
        SceneAnchor { world_pos: Vec3::new(-0.387, -0.720, -2.660), role: Low, quadrant: D },
        SceneAnchor { world_pos: Vec3::new( 0.773, -0.487, -1.380), role: Low, quadrant: B },
        SceneAnchor { world_pos: Vec3::new( 0.387,  0.207, -1.380), role: Low, quadrant: C },
        SceneAnchor { world_pos: Vec3::new( 0.773, -0.950, -2.020), role: Low, quadrant: B },
        SceneAnchor { world_pos: Vec3::new( 0.387, -0.720, -2.660), role: Low, quadrant: D },
        SceneAnchor { world_pos: Vec3::new( 0.000,  0.437, -2.020), role: Low, quadrant: C },
        SceneAnchor { world_pos: Vec3::new( 0.000, -0.027, -2.660), role: Low, quadrant: D },
    ].into_iter().map(|a| SceneAnchor {
        world_pos: scale_anchor_outward(a.world_pos, a.role),
        ..a
    }).collect()
}

fn classify_source_entropy(source_id: &str) -> AnchorRole {
    if source_id.starts_with("camera-")
        || source_id.starts_with("yt-slot-")
        || source_id.starts_with("cbip_")
    {
        AnchorRole::High
    } else if source_id.starts_with("visual-pool-slot-")
        || source_id == "grounding_provenance_ticker"
        || source_id == "precedent_ticker"
        || source_id == "chronicle_ticker"
    {
        AnchorRole::Low
    } else {
        AnchorRole::Medium
    }
}

fn assign_anchor(
    anchors: &[SceneAnchor],
    role: AnchorRole,
    used: &[bool],
) -> Option<usize> {
    let mut best = None;
    let mut best_dist = f32::MAX;
    for (i, anchor) in anchors.iter().enumerate() {
        if used[i] || anchor.role != role {
            continue;
        }
        let d = anchor.world_pos.distance(AOA_CENTROID);
        if d < best_dist {
            best_dist = d;
            best = Some(i);
        }
    }
    best
}

/// GPU shader family used by a scene node.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SceneNodeShader {
    /// Sample the node's content-source texture.
    Textured,
    /// Draw Aperture of Apertures as authored tetrahedral geometry.
    ApertureOfApertures,
}

impl SceneNodeShader {
    pub fn as_f32(self) -> f32 {
        match self {
            SceneNodeShader::Textured => 0.0,
            SceneNodeShader::ApertureOfApertures => 1.0,
        }
    }

    pub fn vertex_count(self) -> u32 {
        match self {
            SceneNodeShader::Textured => 6,
            // Parent tetrahedron plus depth-1, depth-2, and depth-3 children:
            // 85 tetrahedra * 4 triangular panes * 3 vertices.
            SceneNodeShader::ApertureOfApertures => {
                aoa_raw_triangular_pane_count(AOA_TETRIX_RENDER_DEPTH) as u32 * 3
            }
        }
    }
}

/// A quad in 3D space, optionally bound to a content source texture.
#[derive(Debug, Clone)]
pub struct SceneNode {
    pub label: String,
    pub position: Vec3,
    pub scale: Vec3,
    pub rotation_y: f32,
    pub opacity: f32,
    pub shader: SceneNodeShader,
    /// Index into ContentSourceManager's ordered source list.
    /// When None, the renderer uses a placeholder texture.
    pub content_source_id: Option<String>,
    /// AoA pane ordinal targeted by this node's bound content source.
    /// None means the authored AoA anchor renders only its structural geometry.
    pub aoa_payload_pane_ordinal: Option<u32>,
    /// AoA payload density/rendering mode. Only set when the node is a pane-local payload.
    pub aoa_payload_mode: Option<AoaPaneBindingMode>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AoaPaneSceneSource {
    pub source_id: String,
    pub binding: AoaValidatedPaneBinding,
    pub observation: AoaPaneFrameObservation,
    pub lod_alpha: f32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RejectedAoaPaneSceneSource {
    pub source_id: String,
    pub reason: AoaPaneBindingRejectionReason,
}

#[derive(Debug, Clone)]
pub struct BuiltScene {
    pub nodes: Vec<SceneNode>,
    pub aoa_pane_sources: Vec<AoaPaneSceneSource>,
    pub rejected_pane_sources: Vec<RejectedAoaPaneSceneSource>,
}

#[derive(Debug, Clone, PartialEq)]
struct AoaPanePayloadNodeSpec {
    source_id: String,
    pane_id: String,
    pane_ordinal: u32,
    mode: AoaPaneBindingMode,
    opacity: f32,
}

impl SceneNode {
    pub fn new(label: &str) -> Self {
        Self {
            label: label.to_string(),
            position: Vec3::ZERO,
            scale: Vec3::ONE,
            rotation_y: 0.0,
            opacity: 1.0,
            shader: SceneNodeShader::Textured,
            content_source_id: None,
            aoa_payload_pane_ordinal: None,
            aoa_payload_mode: None,
        }
    }

    /// 4x4 model matrix for textured scene planes.
    pub fn model_matrix(&self) -> Mat4 {
        Mat4::from_translation(self.position)
            * Mat4::from_rotation_y(self.rotation_y)
            * Mat4::from_scale(self.scale)
    }
}

// ─── Camera ───────────────────────────────────────────────────────

/// Perspective camera for the 3D scene.
#[derive(Debug, Clone)]
pub struct Camera3D {
    pub eye: Vec3,
    pub target: Vec3,
    pub up: Vec3,
    pub fov_y_radians: f32,
    pub aspect: f32,
    pub near: f32,
    pub far: f32,
    /// Orbital drift radius — camera drifts in a gentle ellipse.
    orbit_radius: f32,
}

impl Camera3D {
    pub fn new(width: u32, height: u32) -> Self {
        Self {
            eye: Vec3::new(0.0, 0.0, 2.0),
            target: Vec3::new(0.0, 0.0, -4.0),
            up: Vec3::Y,
            fov_y_radians: 75.0f32.to_radians(),
            aspect: width as f32 / height as f32,
            near: 0.1,
            far: 50.0,
            orbit_radius: 1.25,
        }
    }

    pub fn view_matrix(&self) -> Mat4 {
        Mat4::look_at_rh(self.eye, self.target, self.up)
    }

    pub fn projection_matrix(&self) -> Mat4 {
        Mat4::perspective_rh(self.fov_y_radians, self.aspect, self.near, self.far)
    }

    fn orbital_pose_at(&self, time: f32, energy: f32) -> (Vec3, Vec3) {
        let period = 72.0 + (1.0 - energy) * 18.0;
        let angle = (time / period) * std::f32::consts::TAU;
        let lateral = angle.sin();
        let depth_dip = 1.0 - lateral * lateral;
        let r = self.orbit_radius + energy * 0.75;
        let vert = 0.20 + energy * 0.30;
        let eye = Vec3::new(
            r * lateral,
            vert * (angle * 0.5).sin(),
            2.06 - 0.38 * depth_dip,
        );
        let target = Vec3::new(
            0.20 * lateral,
            0.10 * (angle * 0.5).sin(),
            -4.0 - 0.24 * depth_dip,
        );
        (eye, target)
    }

    /// Gentle orbital drift — camera traces a wide, slow arc over the scene.
    /// Energy [0,1] modulates orbit radius and vertical amplitude.
    pub fn apply_orbital_drift(&mut self, time: f32) {
        self.apply_orbital_drift_with_energy(time, 0.0);
    }

    pub fn apply_orbital_drift_with_energy(&mut self, time: f32, energy: f32) {
        let e = energy.clamp(0.0, 1.0);
        let (eye, target) = self.orbital_pose_at(time, e);
        self.eye = eye;
        self.target = target;
    }

    /// Moving neon point light: same orbital path as the camera, half-speed,
    /// lifted roughly ten degrees above the eye path.
    pub fn point_light_position(&self, time: f32) -> Vec3 {
        let (eye, target) = self.orbital_pose_at(time * 0.5, 0.0);
        let baseline = eye.distance(target);
        let above = (10.0f32.to_radians().tan() * baseline).clamp(0.75, 1.15);
        eye + Vec3::Y * above
    }
}

// ─── Dynamic scene builders ───────────────────────────────────────

fn source_indices_by_prefix(
    active_sources: &[(&str, f32, i32, u32, u32)],
    prefixes: &[&str],
) -> Vec<usize> {
    active_sources
        .iter()
        .enumerate()
        .filter(|(_, (id, opacity, _, _, _))| {
            *opacity > 0.001 && prefixes.iter().any(|prefix| id.starts_with(prefix))
        })
        .map(|(i, _)| i)
        .collect()
}

fn source_indices_except(
    active_sources: &[(&str, f32, i32, u32, u32)],
    excluded: &[usize],
) -> Vec<usize> {
    active_sources
        .iter()
        .enumerate()
        .filter(|(i, (_, opacity, _, _, _))| *opacity > 0.001 && !excluded.contains(i))
        .map(|(i, _)| i)
        .collect()
}

fn quad_width(height: f32, width: u32, source_height: u32, max_aspect: f32) -> f32 {
    let aspect = width as f32 / source_height.max(1) as f32;
    height * aspect.min(max_aspect)
}

fn make_node(
    active_sources: &[(&str, f32, i32, u32, u32)],
    src_idx: usize,
    position: Vec3,
    height: f32,
    opacity_multiplier: f32,
    rotation_y: f32,
) -> SceneNode {
    let (id, opacity, _, width, source_height) = active_sources[src_idx];
    let mut node = SceneNode::new(id);
    node.position = position;
    node.scale = Vec3::new(quad_width(height, width, source_height, 2.15), height, 1.0);
    node.rotation_y = rotation_y;
    node.opacity = (opacity * opacity_multiplier).clamp(0.0, 1.0);
    node.content_source_id = Some(id.to_string());
    node
}

fn push_optional_node(
    nodes: &mut Vec<SceneNode>,
    active_sources: &[(&str, f32, i32, u32, u32)],
    source_id: &str,
    position: Vec3,
    height: f32,
    opacity_multiplier: f32,
    rotation_y: f32,
) -> bool {
    let Some((src_idx, _)) = active_sources
        .iter()
        .enumerate()
        .find(|(_, (id, opacity, _, _, _))| *opacity > 0.001 && *id == source_id)
    else {
        return false;
    };
    nodes.push(make_node(
        active_sources,
        src_idx,
        position,
        height,
        opacity_multiplier,
        rotation_y,
    ));
    true
}

pub fn authored_aoa_scene_node() -> SceneNode {
    let mut node = SceneNode::new(AOA_NODE_LABEL);
    node.position = Vec3::new(0.0, -0.30, ZPlane::SurfaceScrim.z_position() - 0.06);
    node.scale = Vec3::splat(AOA_BASE_GRID_UNITS);
    node.rotation_y = 0.0;
    node.opacity = 0.92;
    node.shader = SceneNodeShader::ApertureOfApertures;
    node.content_source_id = None;
    node
}

fn push_authored_aoa(nodes: &mut Vec<SceneNode>) {
    let node = authored_aoa_scene_node();
    nodes.push(node);
}

fn push_aoa_pane_payload_nodes(nodes: &mut Vec<SceneNode>, specs: &[AoaPanePayloadNodeSpec]) {
    for spec in specs {
        let mut node = authored_aoa_scene_node();
        node.label = format!("aoa-pane-payload-{}-{}", spec.pane_ordinal, spec.pane_id);
        node.opacity = spec.opacity.clamp(0.0, 1.0);
        node.content_source_id = Some(spec.source_id.clone());
        node.aoa_payload_pane_ordinal = Some(spec.pane_ordinal);
        node.aoa_payload_mode = Some(spec.mode);
        nodes.push(node);
    }
}

pub fn authored_aoa_observation_frame(
    camera: &Camera3D,
    viewport_width: u32,
    viewport_height: u32,
) -> AoaPaneObservationFrame {
    AoaPaneObservationFrame::new(
        authored_aoa_scene_node().model_matrix(),
        camera.view_matrix(),
        camera.projection_matrix(),
        camera.eye,
        viewport_width,
        viewport_height,
    )
}

pub fn observe_authored_aoa_panes(
    camera: &Camera3D,
    viewport_width: u32,
    viewport_height: u32,
) -> Vec<AoaPaneFrameObservation> {
    let manifest = aoa_active_pane_manifest();
    aoa_observe_panes(
        &manifest.panes,
        authored_aoa_observation_frame(camera, viewport_width, viewport_height),
    )
}

fn mark_source_used(
    used_indices: &mut Vec<usize>,
    active_sources: &[(&str, f32, i32, u32, u32)],
    source_id: &str,
) {
    if let Some((idx, _)) = active_sources
        .iter()
        .enumerate()
        .find(|(_, (id, _, _, _, _))| *id == source_id)
    {
        if !used_indices.contains(&idx) {
            used_indices.push(idx);
        }
    }
}

fn is_projection_capable_source(source_id: &str) -> bool {
    matches!(source_id, "imagination-r2" | "overlay-zones")
}

fn mark_projection_capable_sources(
    used_indices: &mut Vec<usize>,
    active_sources: &[(&str, f32, i32, u32, u32)],
) {
    for (idx, (source_id, _, _, _, _)) in active_sources.iter().enumerate() {
        if is_projection_capable_source(source_id) && !used_indices.contains(&idx) {
            used_indices.push(idx);
        }
    }
}

fn push_cube_face(
    nodes: &mut Vec<SceneNode>,
    active_sources: &[(&str, f32, i32, u32, u32)],
    src_idx: usize,
    center: Vec3,
    face: usize,
    height: f32,
    side: f32,
) {
    let (offset, rotation_y, opacity_multiplier) = match face {
        0 => (Vec3::new(0.0, 0.45, 0.0), 0.0, 0.92),
        1 => (Vec3::new(0.0, -0.45, 0.0), 0.0, 0.86),
        2 => (Vec3::new(-side, 0.0, -0.25), 0.46, 0.74),
        3 => (Vec3::new(side, 0.0, -0.25), -0.46, 0.74),
        4 => (Vec3::new(0.0, 0.0, -side * 0.72), 0.0, 0.64),
        _ => (Vec3::new(0.0, 0.0, side * 0.35), 0.0, 0.70),
    };
    nodes.push(make_node(
        active_sources,
        src_idx,
        center + offset,
        height,
        opacity_multiplier,
        rotation_y,
    ));
}

fn push_exploded_cube(
    nodes: &mut Vec<SceneNode>,
    active_sources: &[(&str, f32, i32, u32, u32)],
    source_indices: &[usize],
    center: Vec3,
    face_height: f32,
    side: f32,
) {
    for (face, &src_idx) in source_indices.iter().take(6).enumerate() {
        push_cube_face(
            nodes,
            active_sources,
            src_idx,
            center,
            face,
            face_height,
            side,
        );
    }
}

fn push_deoccluded_grid(
    nodes: &mut Vec<SceneNode>,
    active_sources: &[(&str, f32, i32, u32, u32)],
    source_indices: &[usize],
    center: Vec3,
    columns: usize,
    height: f32,
    x_spacing: f32,
    y_spacing: f32,
    z_spacing: f32,
    opacity_multiplier: f32,
    side_depth_factor: f32,
) {
    if columns == 0 {
        return;
    }

    for (local_idx, &src_idx) in source_indices.iter().enumerate() {
        let col = local_idx % columns;
        let row = local_idx / columns;
        let x = (col as f32 - (columns.saturating_sub(1) as f32 * 0.5)) * x_spacing;
        let y = -(row as f32) * y_spacing;
        let lateral_arc = if columns > 1 && side_depth_factor > 0.0 {
            x.abs() * side_depth_factor
        } else {
            0.0
        };
        let z =
            -(row as f32) * z_spacing + (col as f32 - columns as f32 * 0.5) * 0.04 - lateral_arc;
        let rotation_y = (col as f32 - (columns.saturating_sub(1) as f32 * 0.5)) * -0.08;
        nodes.push(make_node(
            active_sources,
            src_idx,
            center + Vec3::new(x, y, z),
            height,
            opacity_multiplier,
            rotation_y,
        ));
    }
}

fn apply_spatial_drift(nodes: &mut [SceneNode], time: f32) {
    for (i, node) in nodes.iter_mut().enumerate() {
        let phase = (i as f32) * 0.73;
        let is_primary = matches!(
            node.label.as_str(),
            AOA_NODE_LABEL | "grounding_provenance_ticker"
        );

        if is_primary {
            continue;
        }

        // Sinusoidal micro-drift (existing)
        let drift_x = 0.035 * ((time * 0.09 + phase).sin() - phase.sin());
        let drift_y = 0.025 * ((time * 0.07 + phase * 0.9).cos() - (phase * 0.9).cos());
        let drift_z = 0.055 * ((time * 0.06 + phase * 1.4).sin() - (phase * 1.4).sin());
        node.position += Vec3::new(drift_x, drift_y, drift_z);

        // Tensegrity breathing: opacity-driven radial push/pull from AoA centroid.
        // Active sources push outward; fading sources pull inward.
        let to_center = AOA_CENTROID - node.position;
        let dist = to_center.length();
        if dist > 0.1 {
            let strut = (node.opacity - 0.5) * 0.15;
            node.position -= to_center.normalize() * strut;
        }

        if !node.label.starts_with("camera-") {
            node.rotation_y += 0.018 * ((time * 0.05 + phase).sin() - phase.sin());
        }
    }
}

/// Build scene nodes dynamically from active content sources.
///
/// Layout uses tetrahedral anchor points derived from the AoA's stella
/// octangula geometry: 8 cube-vertices for HIGH-entropy sources, 10
/// octahedron/child-centroid points for MEDIUM, 12 trisection points
/// for LOW. Three mandala zones (Utama/Madya/Nista) enforce spatial
/// discipline. Tensegrity breathing modulates radial position by opacity.
pub fn build_scene_from_sources(
    active_sources: &[(&str, f32, i32, u32, u32)], // (id, opacity, z_order, width, height)
    time: f32,
) -> Vec<SceneNode> {
    build_scene_from_source_refs(active_sources, time, false)
}

pub fn build_scene_from_source_records(
    active_sources: &[ActiveContentSourceInfo],
    time: f32,
) -> BuiltScene {
    build_scene_from_source_records_for_stream_posture(
        active_sources,
        time,
        AoaPaneStreamPosture::current(),
    )
}

pub fn build_scene_from_source_records_for_stream_posture(
    active_sources: &[ActiveContentSourceInfo],
    time: f32,
    stream_posture: AoaPaneStreamPosture,
) -> BuiltScene {
    let mut camera = Camera3D::new(1920, 1080);
    camera.apply_orbital_drift(time);
    build_scene_from_source_records_for_stream_posture_with_camera(
        active_sources,
        time,
        stream_posture,
        &camera,
        1920,
        1080,
    )
}

pub fn build_scene_from_source_records_for_stream_posture_with_camera(
    active_sources: &[ActiveContentSourceInfo],
    time: f32,
    stream_posture: AoaPaneStreamPosture,
    camera: &Camera3D,
    viewport_width: u32,
    viewport_height: u32,
) -> BuiltScene {
    let observations = observe_authored_aoa_panes(camera, viewport_width, viewport_height);
    build_scene_from_source_records_for_stream_posture_with_observations(
        active_sources,
        time,
        stream_posture,
        &observations,
    )
}

fn build_scene_from_source_records_for_stream_posture_with_observations(
    active_sources: &[ActiveContentSourceInfo],
    time: f32,
    stream_posture: AoaPaneStreamPosture,
    observations: &[AoaPaneFrameObservation],
) -> BuiltScene {
    let mut ordinary_sources = Vec::new();
    let mut rejected_pane_sources = Vec::new();
    let mut candidates = Vec::new();
    let manifest = aoa_active_pane_manifest();
    let pane_by_ordinal = manifest
        .panes
        .iter()
        .cloned()
        .map(|pane| (pane.pane_ordinal, pane))
        .collect::<HashMap<_, _>>();
    let observation_by_ordinal = observations
        .iter()
        .map(|observation| (observation.pane_ordinal, observation))
        .collect::<HashMap<_, _>>();

    for source in active_sources {
        if source.current_opacity <= 0.001 {
            continue;
        }

        match source.validated_pane_binding_for_stream_posture(stream_posture) {
            Ok(Some(binding)) => {
                let Some(observation) = observation_by_ordinal.get(&binding.pane_ordinal) else {
                    rejected_pane_sources.push(RejectedAoaPaneSceneSource {
                        source_id: source.source_id.clone(),
                        reason: AoaPaneBindingRejectionReason::PaneLodNotPermitted {
                            pane_id: binding.pane_id.clone(),
                            mode: binding.mode,
                            required: aoa_min_lod_for_binding_mode(binding.mode),
                            actual: AoaPaneLodClass::Culled,
                        },
                    });
                    continue;
                };
                let required = aoa_min_lod_for_binding_mode(binding.mode);
                if !aoa_pane_lod_supports_binding_mode(observation.lod_class, binding.mode) {
                    rejected_pane_sources.push(RejectedAoaPaneSceneSource {
                        source_id: source.source_id.clone(),
                        reason: AoaPaneBindingRejectionReason::PaneLodNotPermitted {
                            pane_id: binding.pane_id.clone(),
                            mode: binding.mode,
                            required,
                            actual: observation.lod_class,
                        },
                    });
                    continue;
                }
                let lod_alpha = aoa_pane_lod_alpha_for_binding_mode(observation, binding.mode);
                if lod_alpha <= 0.001 {
                    rejected_pane_sources.push(RejectedAoaPaneSceneSource {
                        source_id: source.source_id.clone(),
                        reason: AoaPaneBindingRejectionReason::PaneLodNotPermitted {
                            pane_id: binding.pane_id.clone(),
                            mode: binding.mode,
                            required,
                            actual: observation.lod_class,
                        },
                    });
                    continue;
                }
                let pane = pane_by_ordinal
                    .get(&binding.pane_ordinal)
                    .expect("validated pane binding should exist in active manifest");
                candidates.push(AoaPanePayloadCandidate {
                    source_id: source.source_id.clone(),
                    binding,
                    observation: (*observation).clone(),
                    pane: pane.clone(),
                    source_opacity: source.current_opacity,
                    lod_alpha,
                });
            }
            Err(reason) => rejected_pane_sources.push(RejectedAoaPaneSceneSource {
                source_id: source.source_id.clone(),
                reason,
            }),
            Ok(None) => ordinary_sources.push(source.scene_tuple()),
        }
    }

    let AoaPanePayloadPlan {
        pane_sources: aoa_pane_sources,
        payload_specs: aoa_pane_payload_specs,
        rejected_sources: subtree_rejections,
    } = plan_aoa_pane_payloads(candidates);
    rejected_pane_sources.extend(subtree_rejections);

    let force_aoa_anchor = !aoa_pane_sources.is_empty();
    let mut nodes = build_scene_from_source_refs(&ordinary_sources, time, force_aoa_anchor);
    push_aoa_pane_payload_nodes(&mut nodes, &aoa_pane_payload_specs);
    BuiltScene {
        nodes,
        aoa_pane_sources,
        rejected_pane_sources,
    }
}

#[derive(Debug, Clone)]
struct AoaPanePayloadCandidate {
    source_id: String,
    binding: AoaValidatedPaneBinding,
    observation: AoaPaneFrameObservation,
    pane: AoaPaneRecord,
    source_opacity: f32,
    lod_alpha: f32,
}

#[derive(Debug, Clone)]
struct AoaPanePayloadPlan {
    pane_sources: Vec<AoaPaneSceneSource>,
    payload_specs: Vec<AoaPanePayloadNodeSpec>,
    rejected_sources: Vec<RejectedAoaPaneSceneSource>,
}

fn plan_aoa_pane_payloads(candidates: Vec<AoaPanePayloadCandidate>) -> AoaPanePayloadPlan {
    let mut accepted: Vec<AoaPanePayloadCandidate> = Vec::new();
    let mut rejected_sources = Vec::new();

    let mut normal = Vec::new();
    let mut accents = Vec::new();
    for candidate in candidates {
        if candidate.binding.mode == AoaPaneBindingMode::EdgeAccent {
            accents.push(candidate);
        } else {
            normal.push(candidate);
        }
    }
    normal.sort_by(|a, b| {
        b.pane
            .depth
            .cmp(&a.pane.depth)
            .then(b.observation.lod_class.cmp(&a.observation.lod_class))
            .then_with(|| {
                b.lod_alpha
                    .partial_cmp(&a.lod_alpha)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then(a.source_id.cmp(&b.source_id))
    });

    for candidate in normal {
        if let Some(selected) = accepted
            .iter()
            .find(|selected| pane_payloads_conflict(&candidate.pane, &selected.pane))
        {
            rejected_sources.push(RejectedAoaPaneSceneSource {
                source_id: candidate.source_id,
                reason: AoaPaneBindingRejectionReason::PaneSubtreeConflict {
                    pane_id: candidate.binding.pane_id,
                    selected_pane_id: selected.binding.pane_id.clone(),
                },
            });
        } else {
            accepted.push(candidate);
        }
    }

    accepted.extend(accents);
    accepted.sort_by(|a, b| a.pane.pane_ordinal.cmp(&b.pane.pane_ordinal));

    let pane_sources = accepted
        .iter()
        .map(|candidate| AoaPaneSceneSource {
            source_id: candidate.source_id.clone(),
            binding: candidate.binding.clone(),
            observation: candidate.observation.clone(),
            lod_alpha: candidate.lod_alpha,
        })
        .collect::<Vec<_>>();
    let payload_specs = accepted
        .iter()
        .map(|candidate| AoaPanePayloadNodeSpec {
            source_id: candidate.source_id.clone(),
            pane_id: candidate.binding.pane_id.clone(),
            pane_ordinal: candidate.binding.pane_ordinal,
            mode: candidate.binding.mode,
            opacity: pane_payload_opacity(
                candidate.source_opacity,
                candidate.lod_alpha,
                candidate.binding.mode,
            ),
        })
        .collect::<Vec<_>>();

    AoaPanePayloadPlan {
        pane_sources,
        payload_specs,
        rejected_sources,
    }
}

fn pane_payloads_conflict(candidate: &AoaPaneRecord, selected: &AoaPaneRecord) -> bool {
    candidate.pane_id == selected.pane_id
        || candidate
            .ancestor_pane_ids
            .iter()
            .any(|ancestor| ancestor == &selected.pane_id)
        || selected
            .ancestor_pane_ids
            .iter()
            .any(|ancestor| ancestor == &candidate.pane_id)
}

fn pane_payload_opacity(source_opacity: f32, lod_alpha: f32, mode: AoaPaneBindingMode) -> f32 {
    let mode_cap = match mode {
        AoaPaneBindingMode::EdgeAccent => 0.28,
        AoaPaneBindingMode::SignalGlyph => 0.42,
        AoaPaneBindingMode::DataGlyph => 0.56,
        AoaPaneBindingMode::TriTextureMasked => 0.88,
    };
    (source_opacity * lod_alpha * mode_cap).clamp(0.0, 1.0)
}

fn build_scene_from_source_refs(
    active_sources: &[(&str, f32, i32, u32, u32)], // (id, opacity, z_order, width, height)
    time: f32,
    force_aoa_anchor: bool,
) -> Vec<SceneNode> {
    let mut nodes = Vec::new();
    let primary_forward = 1.78;
    let on_ring_forward = 2.08;
    let mid_ring_forward = 2.36;
    let far_ring_forward = 2.95;

    let mut used_indices = Vec::new();
    // Full-frame/projection-capable sources can represent prior layouts or
    // broad overlays. They require an explicit role before the baseline 3D
    // layout may place them as ordinary residual quads; otherwise they read as
    // rogue scene reprojections or fake reflections.
    mark_projection_capable_sources(&mut used_indices, active_sources);

    if force_aoa_anchor
        || active_sources
            .iter()
            .any(|(_, opacity, _, _, _)| *opacity > 0.001)
    {
        push_authored_aoa(&mut nodes);
        // Legacy AoA source aliases have historically carried
        // pre-composited camera imagery. The 3D baseline consumes those source
        // IDs so they cannot appear as stale residual quads; the visible anchor
        // is the authored AoA geometry above.
        for source_id in AOA_COMPAT_SOURCE_IDS {
            mark_source_used(&mut used_indices, active_sources, source_id);
        }
    }

    for ticker_id in [
        "grounding_provenance_ticker",
        "precedent_ticker",
        "chronicle_ticker",
    ] {
        if push_optional_node(
            &mut nodes,
            active_sources,
            ticker_id,
            Vec3::new(
                0.0,
                -1.62,
                ZPlane::SurfaceScrim.z_position() - 0.18 + primary_forward,
            ),
            if ticker_id == "grounding_provenance_ticker" {
                0.36
            } else {
                0.48
            },
            0.86,
            0.0,
        ) {
            mark_source_used(&mut used_indices, active_sources, ticker_id);
            break;
        }
    }

    let hls_indices = source_indices_by_prefix(active_sources, &["camera-"])
        .into_iter()
        .filter(|&i| !active_sources[i].0.contains("pi-noir"))
        .collect::<Vec<_>>();
    let ir_indices = source_indices_by_prefix(active_sources, &["camera-pi-noir", "cbip_"]);
    used_indices.extend(hls_indices.iter().copied());
    used_indices.extend(ir_indices.iter().copied());

    let static_camera_artifact_indices =
        source_indices_by_prefix(active_sources, &["visual-pool-slot-"]);
    used_indices.extend(static_camera_artifact_indices.iter().copied());

    // yt-slot sources render on the sphere, not as content quads.
    for (idx, (id, ..)) in active_sources.iter().enumerate() {
        if id.starts_with("yt-slot-") && !used_indices.contains(&idx) {
            used_indices.push(idx);
        }
    }

    // Anchor-based placement: all remaining sources placed at tetrahedral
    // anchor points derived from the AoA's stella octangula geometry.
    let mut all_placeable: Vec<usize> = hls_indices
        .iter()
        .chain(ir_indices.iter())
        .chain(static_camera_artifact_indices.iter())
        .copied()
        .collect();
    let remaining = source_indices_except(active_sources, &used_indices);
    all_placeable.extend(remaining.iter());

    all_placeable.sort_by(|&a, &b| {
        let role_a = classify_source_entropy(active_sources[a].0) as u8;
        let role_b = classify_source_entropy(active_sources[b].0) as u8;
        role_a.cmp(&role_b)
            .then(active_sources[b].2.cmp(&active_sources[a].2))
            .then(a.cmp(&b))
    });

    let anchors = scene_anchors();
    let mut anchor_used = vec![false; anchors.len()];
    for &src_idx in &all_placeable {
        let (id, opacity, _, _, _) = active_sources[src_idx];
        if opacity < 0.001 {
            continue;
        }
        let role = classify_source_entropy(id);
        let height = match role {
            AnchorRole::High => 0.50,
            AnchorRole::Medium => 0.40,
            AnchorRole::Low => 0.20,
        };
        if let Some(ai) = assign_anchor(&anchors, role, &anchor_used) {
            anchor_used[ai] = true;
            nodes.push(make_node(
                active_sources,
                src_idx,
                anchors[ai].world_pos,
                height,
                match role {
                    AnchorRole::High => 1.0,
                    AnchorRole::Medium => 0.72,
                    AnchorRole::Low => 0.30,
                },
                0.0,
            ));
        }
    }

    apply_spatial_drift(&mut nodes, time);
    nodes
}

/// Static proof scene for testing without live content sources.
/// Used when `build_scene_from_sources` receives empty input.
pub fn build_proof_scene() -> Vec<SceneNode> {
    let mut nodes = Vec::new();

    // Camera quad (surface scrim)
    let mut camera = SceneNode::new("proof-camera");
    camera.position = Vec3::new(0.0, 0.0, ZPlane::SurfaceScrim.z_position());
    camera.scale = Vec3::new(1.6 * 1.778, 1.6, 1.0); // 16:9
    camera.opacity = 0.9;
    nodes.push(camera);

    // Ward quads at different depths
    for (i, (label, z_plane, opacity)) in [
        ("proof-ward-0", ZPlane::BeyondScrim, 0.4),
        ("proof-ward-1", ZPlane::MidScrim, 0.6),
        ("proof-ward-2", ZPlane::OnScrim, 0.7),
    ]
    .iter()
    .enumerate()
    {
        let mut ward = SceneNode::new(label);
        ward.position = Vec3::new((i as f32 - 1.0) * 2.0, 0.0, z_plane.z_position());
        ward.scale = Vec3::new(1.5, 1.5, 1.0);
        ward.opacity = *opacity;
        nodes.push(ward);
    }

    // AoA placeholder (mid-scrim, centered)
    let mut aoa = SceneNode::new("proof-aoa");
    aoa.position = Vec3::new(0.0, 0.5, ZPlane::MidScrim.z_position() - 0.5);
    aoa.scale = Vec3::new(AOA_BASE_GRID_UNITS, AOA_BASE_GRID_UNITS, 1.0);
    aoa.opacity = 0.5;
    aoa.shader = SceneNodeShader::ApertureOfApertures;
    nodes.push(aoa);

    nodes
}

// ─── Tests ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::aoa_panes::AoaPaneOcclusionState;
    use crate::content_sources::{
        ActiveContentSourceInfo, AoaPaneBindingMetadata, AoaPaneBindingRejectionReason,
        AoaPaneCompositionPosture, AoaPanePrivacyPosture, AoaPaneSourcePosture,
        AoaPaneStreamPosture,
    };

    fn root_pane_binding_for(pane_id: &str) -> AoaPaneBindingMetadata {
        AoaPaneBindingMetadata {
            pane_id: pane_id.to_string(),
            route: "aoa_pane".to_string(),
            mode: AoaPaneBindingMode::TriTextureMasked,
            clip_policy: Default::default(),
            effect_scope: Default::default(),
            privacy_posture: AoaPanePrivacyPosture::PublicReviewRequired,
            source_posture: AoaPaneSourcePosture::SystemWard,
            composition_posture: AoaPaneCompositionPosture::PaneBoundDeidentified,
            privacy_gate_refs: vec!["fixture:public-review".to_string()],
            face_obscure_upstream_ref: None,
            anti_recognition_ref: None,
            anti_recognition_passed: None,
        }
    }

    fn pane_binding_for(pane_id: &str, mode: AoaPaneBindingMode) -> AoaPaneBindingMetadata {
        let mut binding = root_pane_binding_for(pane_id);
        binding.mode = mode;
        binding
    }

    fn root_pane_binding() -> AoaPaneBindingMetadata {
        root_pane_binding_for("aoa:pane:v1:r:abd")
    }

    fn pane_record_for(pane_id: &str) -> AoaPaneRecord {
        aoa_active_pane_manifest()
            .panes
            .into_iter()
            .find(|pane| pane.pane_id == pane_id)
            .expect("test pane should exist")
    }

    fn pane_observation_for(pane_id: &str, lod_class: AoaPaneLodClass) -> AoaPaneFrameObservation {
        let pane = pane_record_for(pane_id);
        let (projected_area_px2, min_projected_edge_px, facing_dot, visible_fraction) =
            match lod_class {
                AoaPaneLodClass::Text => (12_000.0, 96.0, 0.34, 0.9),
                AoaPaneLodClass::CompactData => (4_800.0, 58.0, 0.26, 0.78),
                AoaPaneLodClass::Glyph => (1_600.0, 32.0, 0.12, 0.68),
                AoaPaneLodClass::Accent => (380.0, 14.0, 0.08, 0.5),
                AoaPaneLodClass::EdgeOnly => (220.0, 7.0, 0.08, 0.5),
                AoaPaneLodClass::Culled => (0.0, 0.0, 0.0, 0.0),
            };
        AoaPaneFrameObservation {
            pane_id: pane.pane_id,
            pane_ordinal: pane.pane_ordinal,
            viewport_px: [1920, 1080],
            screen_bbox_px: [100.0, 100.0, 220.0, 220.0],
            projected_area_px2,
            min_projected_edge_px,
            facing_dot,
            visible_fraction,
            occlusion_state: if lod_class == AoaPaneLodClass::Culled {
                AoaPaneOcclusionState::Hidden
            } else {
                AoaPaneOcclusionState::Visible
            },
            lod_class,
            gate_reasons: Vec::new(),
        }
    }

    #[test]
    fn z_plane_mapping_matches_python_constants() {
        assert!((ZPlane::BeyondScrim.python_float() - 0.2).abs() < 1e-6);
        assert!((ZPlane::MidScrim.python_float() - 0.5).abs() < 1e-6);
        assert!((ZPlane::OnScrim.python_float() - 0.9).abs() < 1e-6);
        assert!((ZPlane::SurfaceScrim.python_float() - 1.0).abs() < 1e-6);
    }

    #[test]
    fn z_positions_are_ordered_by_depth() {
        assert!(ZPlane::BeyondScrim.z_position() < ZPlane::MidScrim.z_position());
        assert!(ZPlane::MidScrim.z_position() < ZPlane::OnScrim.z_position());
        assert!(ZPlane::OnScrim.z_position() < ZPlane::SurfaceScrim.z_position());
    }

    #[test]
    fn camera_projection_is_finite() {
        let cam = Camera3D::new(960, 540);
        let proj = cam.projection_matrix();
        for col in 0..4 {
            for row in 0..4 {
                assert!(proj.col(col)[row].is_finite());
            }
        }
    }

    #[test]
    fn camera_view_is_finite() {
        let cam = Camera3D::new(960, 540);
        let view = cam.view_matrix();
        for col in 0..4 {
            for row in 0..4 {
                assert!(view.col(col)[row].is_finite());
            }
        }
    }

    #[test]
    fn authored_aoa_frame_observations_cover_active_manifest() {
        let cam = Camera3D::new(1920, 1080);
        let observations = observe_authored_aoa_panes(&cam, 1920, 1080);

        assert_eq!(
            observations.len(),
            aoa_raw_triangular_pane_count(AOA_TETRIX_RENDER_DEPTH)
        );
        assert!(observations.iter().any(|observation| {
            matches!(
                observation.lod_class,
                AoaPaneLodClass::Text
                    | AoaPaneLodClass::CompactData
                    | AoaPaneLodClass::Glyph
                    | AoaPaneLodClass::Accent
                    | AoaPaneLodClass::EdgeOnly
            )
        }));
        assert!(observations.iter().all(|observation| {
            observation
                .screen_bbox_px
                .iter()
                .all(|value| value.is_finite())
                && observation.projected_area_px2.is_finite()
                && observation.min_projected_edge_px.is_finite()
                && observation.facing_dot.is_finite()
                && observation.visible_fraction.is_finite()
        }));
    }

    #[test]
    fn authored_aoa_observation_frame_uses_authored_anchor_model() {
        let cam = Camera3D::new(1920, 1080);
        let frame = authored_aoa_observation_frame(&cam, 1920, 1080);
        let node = authored_aoa_scene_node();

        assert_eq!(frame.model_matrix, node.model_matrix());
        assert_eq!(frame.camera_eye, cam.eye);
        assert_eq!(frame.viewport_px, [1920, 1080]);
    }

    #[test]
    fn orbital_drift_stays_bounded() {
        let mut cam = Camera3D::new(960, 540);
        for t in (0..600).map(|i| i as f32 * 0.1) {
            cam.apply_orbital_drift(t);
            assert!(cam.eye.x.abs() < 1.35, "x out of bounds at t={t}");
            assert!(cam.eye.y.abs() < 0.40, "y out of bounds at t={t}");
            assert!(
                (1.65..=2.10).contains(&cam.eye.z),
                "z out of bounds at t={t}: {}",
                cam.eye.z
            );
            assert!(
                (-4.26..=-3.98).contains(&cam.target.z),
                "target z out of bounds at t={t}: {}",
                cam.target.z
            );
        }
    }

    #[test]
    fn point_light_tracks_camera_orbit_above_eye_path() {
        let cam = Camera3D::new(960, 540);
        for t in (0..600).map(|i| i as f32 * 0.1) {
            let (half_speed_eye, _) = cam.orbital_pose_at(t * 0.5, 0.0);
            let light = cam.point_light_position(t);
            assert!(
                (light.x - half_speed_eye.x).abs() < 1e-6,
                "light should share camera orbit x at half-speed"
            );
            assert!(
                (light.z - half_speed_eye.z).abs() < 1e-6,
                "light should share camera orbit z at half-speed"
            );
            assert!(
                light.y > half_speed_eye.y + 0.70,
                "light should stay above camera path"
            );
        }
    }

    #[test]
    fn model_matrix_identity_at_origin() {
        let node = SceneNode::new("test");
        let mat = node.model_matrix();
        let identity = Mat4::IDENTITY;
        for col in 0..4 {
            for row in 0..4 {
                assert!(
                    (mat.col(col)[row] - identity.col(col)[row]).abs() < 1e-6,
                    "mismatch at [{col}][{row}]"
                );
            }
        }
    }

    #[test]
    fn model_matrix_includes_position() {
        let mut node = SceneNode::new("test");
        node.position = Vec3::new(1.0, 2.0, -3.0);
        let mat = node.model_matrix();
        assert!((mat.col(3)[0] - 1.0).abs() < 1e-6);
        assert!((mat.col(3)[1] - 2.0).abs() < 1e-6);
        assert!((mat.col(3)[2] - (-3.0)).abs() < 1e-6);
    }

    #[test]
    fn proof_scene_has_five_nodes() {
        let scene = build_proof_scene();
        assert_eq!(scene.len(), 5);
    }

    #[test]
    fn proof_scene_uses_authored_aoa_shader() {
        let scene = build_proof_scene();
        let aoa = scene.iter().find(|node| node.label == "proof-aoa").unwrap();
        assert_eq!(aoa.shader, SceneNodeShader::ApertureOfApertures);
        assert_eq!(aoa.scale.x, AOA_BASE_GRID_UNITS);
        assert_eq!(aoa.scale.y, AOA_BASE_GRID_UNITS);
    }

    #[test]
    fn aoa_shader_family_draws_volumetric_triangle_panes() {
        assert_eq!(SceneNodeShader::Textured.vertex_count(), 6);
        assert_eq!(
            SceneNodeShader::ApertureOfApertures.vertex_count(),
            aoa_raw_triangular_pane_count(AOA_TETRIX_RENDER_DEPTH) as u32 * 3
        );
    }

    #[test]
    fn aoa_tetrix_geometry_counts_are_pinned() {
        assert_eq!(AOA_TETRIX_RENDER_DEPTH, 3);
        assert_eq!(aoa_leaf_tetrahedron_count(AOA_TETRIX_RENDER_DEPTH), 64);
        assert_eq!(aoa_total_tetrahedron_count(AOA_TETRIX_RENDER_DEPTH), 85);
        assert_eq!(aoa_raw_edge_segment_count(AOA_TETRIX_RENDER_DEPTH), 510);
        assert_eq!(aoa_raw_triangular_pane_count(AOA_TETRIX_RENDER_DEPTH), 340);
    }

    #[test]
    fn aoa_shader_uses_current_identity_not_legacy_names() {
        let shader = include_str!("shaders/scene_quad.wgsl");
        assert!(
            !shader.to_ascii_lowercase().contains("sierpinski"),
            "the authored 3D anchor shader must use AoA/tetrix naming only"
        );
        assert!(
            shader.contains("child_tetra_vertex")
                && shader.contains("aoa_vertex")
                && shader.contains("aoa_fragment"),
            "AoA mesh shader entry points should remain explicit"
        );
        assert!(
            shader.contains("AOA_INNER_PANE_COUNT_DEPTH_3")
                && shader.contains("aoa_pane_depth")
                && shader.contains("aoa_neon_palette"),
            "AoA shader must carry the depth-3 pane layer and temporary per-volume color differentiation"
        );
    }

    #[test]
    fn aoa_shader_samples_payloads_only_as_pane_local_content() {
        let shader = include_str!("shaders/scene_quad.wgsl");
        for required in [
            "payload_pane_ordinal",
            "payload_mode",
            "pane_payload_sample_uv",
            "quantized_payload_sample_uv",
            "let safe_cells = max(cells, 1.0)",
            "let cell = clamp(",
            "textureSample(quad_texture, quad_sampler, sample_uv)",
            "current_pane != target_pane",
            "triangle_inside_mask_from_barycentric",
        ] {
            assert!(
                shader.contains(required),
                "AoA payload shader should stay pane-local and source-bound: missing {required}"
            );
        }
    }

    #[test]
    fn aoa_shader_declares_usable_triangular_pane_topology() {
        let shader = include_str!("shaders/scene_quad.wgsl");
        for required in [
            "AOA_OUTER_PANE_COUNT",
            "AOA_INNER_PANE_COUNT_DEPTH_1",
            "AOA_INNER_PANE_COUNT_DEPTH_2",
            "AOA_DEPTH_2_PANES_PER_CHILD",
            "aoa_vertex",
            "aoa_face_vertex",
            "grandchild_idx",
            "triangle_barycentric",
            "triangle_inside_mask_from_barycentric",
            "pane_information_uv_from_barycentric",
            "pane_information_grid",
            "aoa_fragment",
            "inner_pane",
        ] {
            assert!(
                shader.contains(required),
                "AoA shader should keep pane affordance vocabulary: missing {required}"
            );
        }
    }

    #[test]
    fn aoa_scene_shader_parses_with_naga() {
        let shader = include_str!("shaders/scene_quad.wgsl");
        naga::front::wgsl::parse_str(shader).expect("scene quad WGSL should parse");
    }

    #[test]
    fn ndc_depth_ordering() {
        let cam = Camera3D::new(960, 540);
        let vp = cam.projection_matrix() * cam.view_matrix();

        let far_z = ZPlane::BeyondScrim.z_position();
        let near_z = ZPlane::SurfaceScrim.z_position();

        let far_ndc = vp * glam::Vec4::new(0.0, 0.0, far_z, 1.0);
        let near_ndc = vp * glam::Vec4::new(0.0, 0.0, near_z, 1.0);

        let far_depth = far_ndc.z / far_ndc.w;
        let near_depth = near_ndc.z / near_ndc.w;

        assert!(
            far_depth > near_depth,
            "beyond-scrim (z={far_z}) should have larger NDC depth than surface (z={near_z})"
        );
    }

    // ── Phase 1 tests ──────────────────────────────────────────────

    #[test]
    fn z_plane_from_z_order_mapping() {
        assert_eq!(ZPlane::from_z_order(0), ZPlane::BeyondScrim);
        assert_eq!(ZPlane::from_z_order(2), ZPlane::BeyondScrim);
        assert_eq!(ZPlane::from_z_order(3), ZPlane::MidScrim);
        assert_eq!(ZPlane::from_z_order(5), ZPlane::OnScrim);
        assert_eq!(ZPlane::from_z_order(7), ZPlane::OnScrim);
        assert_eq!(ZPlane::from_z_order(8), ZPlane::SurfaceScrim);
        assert_eq!(ZPlane::from_z_order(10), ZPlane::SurfaceScrim);
    }

    #[test]
    fn dynamic_scene_from_sources() {
        let sources = vec![
            ("camera-brio-operator", 0.8f32, 5i32, 640u32, 360u32),
            ("camera-c920-overhead", 0.6, 5, 640, 360),
            ("content-episodic_recall", 0.4, 3, 1920, 1080),
        ];
        let refs: Vec<(&str, f32, i32, u32, u32)> = sources
            .iter()
            .map(|&(id, op, z, w, h)| (id, op, z, w, h))
            .collect();
        let scene = build_scene_from_sources(&refs, 0.0);

        assert_eq!(
            scene.len(),
            4,
            "should have 3 source nodes plus the authored AoA anchor"
        );

        let ids: Vec<&str> = scene.iter().map(|n| n.label.as_str()).collect();
        assert!(ids.contains(&AOA_NODE_LABEL));
        assert!(
            ids.contains(&"content-episodic_recall"),
            "content should be present"
        );
        assert!(
            ids.contains(&"camera-brio-operator"),
            "camera brio should be present"
        );
        assert!(
            ids.contains(&"camera-c920-overhead"),
            "camera c920 should be present"
        );

        let content = scene
            .iter()
            .find(|n| n.label == "content-episodic_recall")
            .unwrap();
        let dist_to_aoa = content.position.distance(AOA_CENTROID);
        assert!(
            dist_to_aoa > UTAMA_RADIUS,
            "content must be outside Utama zone (dist={dist_to_aoa})"
        );
    }

    #[test]
    fn dynamic_scene_skips_invisible() {
        let sources = vec![
            ("camera-brio", 0.0f32, 5i32, 640u32, 360u32),
            ("camera-c920", 0.5, 5, 640, 360),
        ];
        let refs: Vec<(&str, f32, i32, u32, u32)> = sources
            .iter()
            .map(|&(id, op, z, w, h)| (id, op, z, w, h))
            .collect();
        let scene = build_scene_from_sources(&refs, 0.0);
        assert_eq!(
            scene.len(),
            2,
            "invisible source should be skipped, with authored AoA retained"
        );
        assert!(scene.iter().all(|n| n.label != "camera-brio"));
        assert!(scene.iter().any(|n| n.label == "camera-c920"));
    }

    #[test]
    fn dynamic_scene_preserves_aspect_ratio() {
        let sources = vec![("cam", 1.0f32, 8i32, 1920u32, 1080u32)];
        let refs: Vec<(&str, f32, i32, u32, u32)> = sources
            .iter()
            .map(|&(id, op, z, w, h)| (id, op, z, w, h))
            .collect();
        let scene = build_scene_from_sources(&refs, 0.0);
        let cam = scene.iter().find(|n| n.label == "cam").unwrap();
        let aspect = cam.scale.x / cam.scale.y;
        assert!(
            (aspect - 1920.0 / 1080.0).abs() < 0.01,
            "aspect ratio should be preserved"
        );
    }

    #[test]
    fn dynamic_scene_content_source_ids() {
        let sources = vec![
            ("camera-brio", 0.5f32, 5i32, 640u32, 360u32),
            ("content-recall", 0.4, 3, 1920, 1080),
        ];
        let refs: Vec<(&str, f32, i32, u32, u32)> = sources
            .iter()
            .map(|&(id, op, z, w, h)| (id, op, z, w, h))
            .collect();
        let scene = build_scene_from_sources(&refs, 0.0);
        let ids: Vec<&str> = scene
            .iter()
            .filter_map(|n| n.content_source_id.as_deref())
            .collect();
        assert!(ids.contains(&"content-recall"));
        assert!(ids.contains(&"camera-brio"));
    }

    #[test]
    fn pane_bound_source_is_consumed_by_aoa_not_residual_quad() {
        let records = vec![
            ActiveContentSourceInfo::new("pane-source", 0.9, 9, 320, 180)
                .with_pane_binding(root_pane_binding()),
            ActiveContentSourceInfo::new("camera-brio", 0.8, 5, 1280, 720),
        ];

        let built = build_scene_from_source_records(&records, 0.0);

        assert_eq!(built.aoa_pane_sources.len(), 1);
        assert_eq!(built.aoa_pane_sources[0].source_id, "pane-source");
        assert_eq!(built.aoa_pane_sources[0].binding.pane_ordinal, 0);
        assert!(built.rejected_pane_sources.is_empty());
        assert!(
            built.nodes.iter().all(|node| {
                node.content_source_id.as_deref() != Some("pane-source")
                    || (node.shader == SceneNodeShader::ApertureOfApertures
                        && node.aoa_payload_pane_ordinal == Some(0))
            }),
            "pane-bound source must only appear as a selected AoA pane payload"
        );
        assert!(
            built.nodes.iter().any(|node| node.label == AOA_NODE_LABEL),
            "a valid pane-bound source should keep the authored AoA anchor active"
        );
        let payload = built
            .nodes
            .iter()
            .find(|node| node.aoa_payload_pane_ordinal == Some(0))
            .expect("valid pane-bound source should produce a pane payload node");
        assert_eq!(payload.shader, SceneNodeShader::ApertureOfApertures);
        assert_eq!(payload.content_source_id.as_deref(), Some("pane-source"));
        assert_eq!(
            payload.model_matrix(),
            authored_aoa_scene_node().model_matrix(),
            "pane payloads must ride the authored AoA transform, not viewport coordinates"
        );
    }

    #[test]
    fn four_root_panes_can_receive_distinct_source_bound_payloads() {
        let root_panes = [
            ("pane-abd", "aoa:pane:v1:r:abd", 0u32),
            ("pane-bcd", "aoa:pane:v1:r:bcd", 1u32),
            ("pane-cad", "aoa:pane:v1:r:cad", 2u32),
            ("pane-acb", "aoa:pane:v1:r:acb", 3u32),
        ];
        let records = root_panes
            .iter()
            .map(|(source_id, pane_id, _)| {
                ActiveContentSourceInfo::new(*source_id, 0.9, 9, 320, 180)
                    .with_pane_binding(root_pane_binding_for(pane_id))
            })
            .collect::<Vec<_>>();
        let observations = root_panes
            .iter()
            .map(|(_, pane_id, _)| pane_observation_for(pane_id, AoaPaneLodClass::Text))
            .collect::<Vec<_>>();

        let built = build_scene_from_source_records_for_stream_posture_with_observations(
            &records,
            0.0,
            AoaPaneStreamPosture::Public,
            &observations,
        );
        let mut payload_ordinals = built
            .nodes
            .iter()
            .filter_map(|node| node.aoa_payload_pane_ordinal)
            .collect::<Vec<_>>();
        payload_ordinals.sort_unstable();

        assert_eq!(payload_ordinals, vec![0, 1, 2, 3]);
        for (source_id, _, ordinal) in root_panes {
            let payload = built
                .nodes
                .iter()
                .find(|node| node.aoa_payload_pane_ordinal == Some(ordinal))
                .expect("each root pane should have a payload node");
            assert_eq!(payload.content_source_id.as_deref(), Some(source_id));
            assert_eq!(payload.shader, SceneNodeShader::ApertureOfApertures);
        }
        assert_eq!(
            built
                .nodes
                .iter()
                .filter(|node| node.label == AOA_NODE_LABEL)
                .count(),
            1,
            "payload passes should supplement, not replace or duplicate, the authored anchor"
        );
    }

    #[test]
    fn inner_pane_payload_is_consumed_but_rejected_until_lod_gate_permits_it() {
        let inner_pane_id = "aoa:pane:v1:a.d:bcd";
        let records = vec![
            ActiveContentSourceInfo::new("inner-accent", 0.9, 9, 320, 180).with_pane_binding(
                pane_binding_for(inner_pane_id, AoaPaneBindingMode::EdgeAccent),
            ),
            ActiveContentSourceInfo::new("camera-brio", 0.8, 5, 1280, 720),
        ];
        let blocked = build_scene_from_source_records_for_stream_posture_with_observations(
            &records,
            0.0,
            AoaPaneStreamPosture::Public,
            &[pane_observation_for(
                inner_pane_id,
                AoaPaneLodClass::EdgeOnly,
            )],
        );

        assert!(blocked.aoa_pane_sources.is_empty());
        assert_eq!(
            blocked.rejected_pane_sources[0].reason,
            AoaPaneBindingRejectionReason::PaneLodNotPermitted {
                pane_id: inner_pane_id.to_string(),
                mode: AoaPaneBindingMode::EdgeAccent,
                required: AoaPaneLodClass::Accent,
                actual: AoaPaneLodClass::EdgeOnly,
            }
        );
        assert!(
            blocked
                .nodes
                .iter()
                .all(|node| node.content_source_id.as_deref() != Some("inner-accent")),
            "LOD-rejected inner pane content must be consumed, not projected as a fallback quad"
        );

        let accepted = build_scene_from_source_records_for_stream_posture_with_observations(
            &records,
            0.0,
            AoaPaneStreamPosture::Public,
            &[pane_observation_for(inner_pane_id, AoaPaneLodClass::Accent)],
        );

        assert_eq!(accepted.aoa_pane_sources.len(), 1);
        assert!(
            accepted.aoa_pane_sources[0].lod_alpha > 0.0,
            "accepted inner pane payload should carry a smooth LOD alpha"
        );
        let payload = accepted
            .nodes
            .iter()
            .find(|node| node.content_source_id.as_deref() == Some("inner-accent"))
            .expect("LOD-permitted inner pane should produce a pane payload node");
        assert_eq!(
            payload.aoa_payload_mode,
            Some(AoaPaneBindingMode::EdgeAccent)
        );
        assert_eq!(
            payload.aoa_payload_pane_ordinal,
            Some(pane_record_for(inner_pane_id).pane_ordinal)
        );
        assert!(
            payload.opacity <= 0.9 * 0.28,
            "inner accents must stay low-alpha rather than becoming full pane cards"
        );
    }

    #[test]
    fn normal_parent_and_child_payloads_are_mutually_exclusive() {
        let root_id = "aoa:pane:v1:r:abd";
        let child_id = "aoa:pane:v1:a:abd";
        let records = vec![
            ActiveContentSourceInfo::new("root-full", 0.9, 9, 640, 360).with_pane_binding(
                pane_binding_for(root_id, AoaPaneBindingMode::TriTextureMasked),
            ),
            ActiveContentSourceInfo::new("child-data", 0.9, 9, 320, 180)
                .with_pane_binding(pane_binding_for(child_id, AoaPaneBindingMode::DataGlyph)),
        ];

        let built = build_scene_from_source_records_for_stream_posture_with_observations(
            &records,
            0.0,
            AoaPaneStreamPosture::Public,
            &[
                pane_observation_for(root_id, AoaPaneLodClass::Text),
                pane_observation_for(child_id, AoaPaneLodClass::CompactData),
            ],
        );

        assert_eq!(built.aoa_pane_sources.len(), 1);
        assert_eq!(built.aoa_pane_sources[0].source_id, "child-data");
        assert_eq!(
            built.rejected_pane_sources[0].reason,
            AoaPaneBindingRejectionReason::PaneSubtreeConflict {
                pane_id: root_id.to_string(),
                selected_pane_id: child_id.to_string(),
            }
        );
        assert!(
            built
                .nodes
                .iter()
                .all(|node| node.content_source_id.as_deref() != Some("root-full")),
            "excluded parent payload must not leak back as a residual surface"
        );
    }

    #[test]
    fn low_alpha_child_accents_can_coexist_with_parent_payloads() {
        let root_id = "aoa:pane:v1:r:abd";
        let child_id = "aoa:pane:v1:a.d:abd";
        let records = vec![
            ActiveContentSourceInfo::new("root-full", 0.9, 9, 640, 360).with_pane_binding(
                pane_binding_for(root_id, AoaPaneBindingMode::TriTextureMasked),
            ),
            ActiveContentSourceInfo::new("child-accent", 0.9, 9, 320, 180)
                .with_pane_binding(pane_binding_for(child_id, AoaPaneBindingMode::EdgeAccent)),
        ];

        let built = build_scene_from_source_records_for_stream_posture_with_observations(
            &records,
            0.0,
            AoaPaneStreamPosture::Public,
            &[
                pane_observation_for(root_id, AoaPaneLodClass::Text),
                pane_observation_for(child_id, AoaPaneLodClass::Accent),
            ],
        );
        let payload_sources = built
            .nodes
            .iter()
            .filter_map(|node| node.content_source_id.as_deref())
            .collect::<Vec<_>>();

        assert!(built.rejected_pane_sources.is_empty());
        assert!(payload_sources.contains(&"root-full"));
        assert!(payload_sources.contains(&"child-accent"));
        assert!(
            built
                .nodes
                .iter()
                .find(|node| node.content_source_id.as_deref() == Some("child-accent"))
                .unwrap()
                .opacity
                < 0.28,
            "child accent exception must remain a low-alpha accent"
        );
    }

    #[test]
    fn rejected_pane_bound_source_is_still_consumed_not_residual_quad() {
        let mut bad_binding = root_pane_binding();
        bad_binding.route = "fullscreen".to_string();
        let records = vec![
            ActiveContentSourceInfo::new("bad-pane-source", 0.9, 9, 320, 180)
                .with_pane_binding(bad_binding),
            ActiveContentSourceInfo::new("camera-brio", 0.8, 5, 1280, 720),
        ];

        let built = build_scene_from_source_records(&records, 0.0);

        assert!(built.aoa_pane_sources.is_empty());
        assert_eq!(built.rejected_pane_sources.len(), 1);
        assert_eq!(built.rejected_pane_sources[0].source_id, "bad-pane-source");
        assert_eq!(
            built.rejected_pane_sources[0].reason,
            AoaPaneBindingRejectionReason::InvalidRoute("fullscreen".to_string())
        );
        assert!(
            built
                .nodes
                .iter()
                .all(|node| node.label != "bad-pane-source"),
            "rejected pane bindings must fail closed rather than becoming residual quads"
        );
    }

    #[test]
    fn private_pane_bound_source_is_blocked_in_public_without_residual_quad() {
        let mut private_binding = root_pane_binding();
        private_binding.privacy_posture = AoaPanePrivacyPosture::PrivateOnly;
        let records = vec![
            ActiveContentSourceInfo::new("private-sentinel-pane", 0.9, 9, 320, 180)
                .with_pane_binding(private_binding),
            ActiveContentSourceInfo::new("camera-brio", 0.8, 5, 1280, 720),
        ];

        let built = build_scene_from_source_records_for_stream_posture(
            &records,
            0.0,
            AoaPaneStreamPosture::Public,
        );

        assert!(built.aoa_pane_sources.is_empty());
        assert_eq!(built.rejected_pane_sources.len(), 1);
        assert_eq!(
            built.rejected_pane_sources[0].reason,
            AoaPaneBindingRejectionReason::PrivateOnlyInPublicMode
        );
        assert!(
            built
                .nodes
                .iter()
                .all(|node| node.label != "private-sentinel-pane"),
            "private sentinel content must fail closed in public mode, not become a fallback quad"
        );
    }

    #[test]
    fn operator_camera_pane_bound_source_requires_face_obscure_and_anti_recognition() {
        let mut camera_binding = root_pane_binding();
        camera_binding.source_posture = AoaPaneSourcePosture::OperatorCamera;
        let records = vec![
            ActiveContentSourceInfo::new("operator-camera-pane", 0.9, 9, 320, 180)
                .with_pane_binding(camera_binding),
            ActiveContentSourceInfo::new("camera-brio", 0.8, 5, 1280, 720),
        ];

        let built = build_scene_from_source_records_for_stream_posture(
            &records,
            0.0,
            AoaPaneStreamPosture::Public,
        );

        assert!(built.aoa_pane_sources.is_empty());
        assert_eq!(built.rejected_pane_sources.len(), 1);
        assert_eq!(
            built.rejected_pane_sources[0].reason,
            AoaPaneBindingRejectionReason::OperatorCameraFaceObscureMissing
        );
        assert!(
            built
                .nodes
                .iter()
                .all(|node| node.label != "operator-camera-pane"),
            "camera-derived pane payloads must not bypass upstream privacy evidence"
        );
    }

    #[test]
    fn host_framed_pane_bound_source_is_rejected_not_projected() {
        let mut host_binding = root_pane_binding();
        host_binding.composition_posture = AoaPaneCompositionPosture::HostFraming;
        let records = vec![
            ActiveContentSourceInfo::new("host-framed-pane", 0.9, 9, 320, 180)
                .with_pane_binding(host_binding),
            ActiveContentSourceInfo::new("camera-brio", 0.8, 5, 1280, 720),
        ];

        let built = build_scene_from_source_records_for_stream_posture(
            &records,
            0.0,
            AoaPaneStreamPosture::Public,
        );

        assert!(built.aoa_pane_sources.is_empty());
        assert_eq!(
            built.rejected_pane_sources[0].reason,
            AoaPaneBindingRejectionReason::AntiParasocialComposition("HostFraming".to_string())
        );
        assert!(
            built
                .nodes
                .iter()
                .all(|node| node.label != "host-framed-pane"),
            "host-framed pane content must not degrade into a residual viewer-address tile"
        );
    }

    #[test]
    fn requested_geometric_layout_places_primary_elements() {
        let sources = vec![
            (AOA_NODE_LABEL, 0.9f32, 4i32, 1280u32, 720u32),
            ("sierpinski", 0.8f32, 3i32, 840u32, 840u32),
            ("imagination-r2", 0.3f32, 10i32, 1920u32, 1080u32),
            ("overlay-zones", 0.5f32, 2i32, 1280u32, 720u32),
            ("grounding_provenance_ticker", 0.8, 3, 480, 40),
            ("camera-brio-operator", 0.8, 5, 1280, 720),
            ("camera-c920-overhead", 0.8, 5, 1280, 720),
            ("camera-pi-noir-desk", 0.8, 5, 640, 360),
            ("cbip_dual_ir_displacement", 0.8, 5, 640, 480),
            ("programme_history", 0.7, 3, 440, 140),
            ("m8_oscilloscope", 0.7, 3, 512, 320),
        ];
        let scene = build_scene_from_sources(&sources, 0.0);

        let aoa = scene.iter().find(|n| n.label == AOA_NODE_LABEL).unwrap();
        assert!(aoa.position.x.abs() < 0.01);
        assert!(
            (-0.42..=-0.22).contains(&aoa.position.y),
            "AoA should sit low enough to read as a grounded foreground object"
        );
        assert!(
            aoa.position.z > ZPlane::SurfaceScrim.z_position() - 0.5,
            "AoA should be near the surface scrim"
        );
        assert_eq!(aoa.rotation_y, 0.0);
        assert_eq!(aoa.shader, SceneNodeShader::ApertureOfApertures);
        assert_eq!(aoa.scale.x, AOA_BASE_GRID_UNITS);
        assert_eq!(aoa.scale.y, AOA_BASE_GRID_UNITS);
        assert_eq!(aoa.scale.z, AOA_BASE_GRID_UNITS);
        assert!(
            aoa.content_source_id.is_none(),
            "central AoA must be authored geometry, not a sampled source texture"
        );
        assert!(
            scene.iter().all(|n| n.label != "sierpinski"),
            "baseline layout must not re-project the legacy AoA alias as a residual object"
        );
        assert!(
            scene
                .iter()
                .all(|n| n.label != "imagination-r2" && n.label != "overlay-zones"),
            "projection-capable sources need explicit roles, not default residual quads"
        );

        let ticker = scene
            .iter()
            .find(|n| n.label == "grounding_provenance_ticker")
            .unwrap();
        assert!(ticker.position.y < aoa.position.y);

        let hls = scene
            .iter()
            .find(|n| n.label == "camera-brio-operator")
            .unwrap();
        let hls_dist = hls.position.distance(AOA_CENTROID);
        assert!(
            hls_dist > UTAMA_RADIUS,
            "camera must be outside Utama (dist={hls_dist})"
        );

        let ir = scene
            .iter()
            .find(|n| n.label == "camera-pi-noir-desk")
            .unwrap();
        let ir_dist = ir.position.distance(AOA_CENTROID);
        assert!(
            ir_dist > UTAMA_RADIUS,
            "IR must be outside Utama (dist={ir_dist})"
        );

        let ward = scene
            .iter()
            .find(|n| n.label == "programme_history")
            .unwrap();
        let ward_dist = ward.position.distance(AOA_CENTROID);
        assert!(
            ward_dist > UTAMA_RADIUS,
            "ward must be outside Utama (dist={ward_dist})"
        );
    }

    #[test]
    fn legacy_aoa_alias_source_cannot_project_stale_texture() {
        let sources = vec![
            ("sierpinski", 0.8f32, 3i32, 840u32, 840u32),
            ("camera-brio-operator", 0.8, 5, 1280, 720),
            ("programme_history", 0.7, 3, 440, 140),
        ];
        let scene = build_scene_from_sources(&sources, 0.0);
        let aoa = scene.iter().find(|n| n.label == AOA_NODE_LABEL).unwrap();

        assert_eq!(aoa.shader, SceneNodeShader::ApertureOfApertures);
        assert!(
            aoa.content_source_id.is_none(),
            "legacy AoA alias source may request AoA, but must not supply its pixels"
        );
        assert!(
            scene.iter().all(|n| n.label != "sierpinski"),
            "legacy AoA alias texture must be consumed, not placed as a residual tile"
        );
    }

    #[test]
    fn surrounding_content_uses_depth_without_passing_legacy_aoa_alias() {
        let sources = vec![
            (AOA_NODE_LABEL, 0.9f32, 4i32, 1280u32, 720u32),
            ("grounding_provenance_ticker", 0.8, 3, 480, 40),
            ("camera-brio-operator", 0.8, 5, 1280, 720),
            ("camera-c920-overhead", 0.8, 5, 1280, 720),
            ("camera-pi-noir-desk", 0.8, 5, 640, 360),
            ("cbip_dual_ir_displacement", 0.8, 5, 640, 480),
            ("programme_history", 0.7, 3, 440, 140),
            ("m8_oscilloscope", 0.7, 3, 512, 320),
            ("ward-c", 0.7, 3, 420, 140),
            ("ward-d", 0.7, 3, 420, 140),
            ("ward-e", 0.7, 3, 420, 140),
            ("ward-f", 0.7, 3, 420, 140),
        ];
        let scene = build_scene_from_sources(&sources, 0.0);
        let aoa_z = scene
            .iter()
            .find(|n| n.label == AOA_NODE_LABEL)
            .unwrap()
            .position
            .z;

        let hls = scene
            .iter()
            .find(|n| n.label == "camera-brio-operator")
            .unwrap();
        assert!(
            hls.position.is_finite(),
            "HLS camera should be placed at a finite anchor position"
        );

        let ir = scene
            .iter()
            .find(|n| n.label == "camera-pi-noir-desk")
            .unwrap();
        assert!(
            ir.position.is_finite(),
            "IR feed should be placed at a finite anchor position"
        );

        let ward = scene
            .iter()
            .find(|n| n.label == "programme_history")
            .unwrap();
        assert!(
            ward.position.distance(AOA_CENTROID) > UTAMA_RADIUS,
            "wards must be outside Utama zone"
        );
    }

    #[test]
    fn cameras_placed_at_distinct_anchor_positions() {
        let sources = vec![
            (AOA_NODE_LABEL, 0.9f32, 4i32, 1280u32, 720u32),
            ("camera-pi-noir-left", 0.8, 5, 640, 360),
            ("camera-pi-noir-center", 0.8, 5, 640, 360),
            ("camera-pi-noir-right", 0.8, 5, 640, 360),
        ];
        let scene = build_scene_from_sources(&sources, 0.0);
        let cams: Vec<&SceneNode> = scene
            .iter()
            .filter(|n| n.label.starts_with("camera-"))
            .collect();
        assert_eq!(cams.len(), 3, "all 3 cameras should be placed");
        for (i, a) in cams.iter().enumerate() {
            for b in cams.iter().skip(i + 1) {
                assert!(
                    a.position.distance(b.position) > 0.1,
                    "cameras at distinct anchor points must not overlap: {} vs {}",
                    a.label, b.label,
                );
            }
        }
    }

    #[test]
    fn static_camera_artifacts_do_not_read_as_live_camera_tiles() {
        let sources = vec![
            (AOA_NODE_LABEL, 0.9f32, 4i32, 1280u32, 720u32),
            ("grounding_provenance_ticker", 0.8, 3, 480, 40),
            ("camera-brio-operator", 0.8, 5, 1280, 720),
            ("camera-c920-overhead", 0.8, 5, 1280, 720),
            ("visual-pool-slot-0", 0.9, 5, 640, 360),
            ("programme_history", 0.7, 3, 440, 140),
            ("m8_oscilloscope", 0.7, 3, 512, 320),
            ("ward-c", 0.7, 3, 420, 140),
            ("ward-d", 0.7, 3, 420, 140),
        ];
        let scene = build_scene_from_sources(&sources, 0.0);
        let live_camera = scene
            .iter()
            .find(|n| n.label == "camera-brio-operator")
            .unwrap();
        let static_artifact = scene
            .iter()
            .find(|n| n.label == "visual-pool-slot-0")
            .unwrap();
        let primary_ward = scene
            .iter()
            .find(|n| n.label == "programme_history")
            .unwrap();

        assert!(
            static_artifact.opacity < live_camera.opacity,
            "static artifacts should have lower visual authority than live cameras"
        );
        assert!(
            static_artifact.scale.y < live_camera.scale.y,
            "static artifacts should be smaller than live camera tiles"
        );
    }

    #[test]
    fn deoccluded_baseline_spreads_sources_within_each_layer() {
        let sources = vec![
            (AOA_NODE_LABEL, 0.9f32, 4i32, 1280u32, 720u32),
            ("grounding_provenance_ticker", 0.8, 3, 480, 40),
            ("camera-brio-operator", 0.8, 5, 1280, 720),
            ("camera-c920-overhead", 0.8, 5, 1280, 720),
            ("camera-side", 0.8, 5, 1280, 720),
            ("camera-mpc", 0.8, 5, 1280, 720),
            ("camera-pi-noir-desk", 0.8, 5, 640, 360),
            ("camera-pi-noir-chessboard", 0.8, 5, 640, 360),
            ("cbip_dual_ir_displacement", 0.8, 5, 640, 480),
            ("ward-a", 0.7, 3, 420, 140),
            ("ward-b", 0.7, 3, 420, 140),
            ("ward-c", 0.7, 3, 420, 140),
            ("ward-d", 0.7, 3, 420, 140),
            ("ward-e", 0.7, 3, 420, 140),
            ("ward-f", 0.7, 3, 420, 140),
            ("ward-g", 0.7, 3, 420, 140),
            ("ward-h", 0.7, 3, 420, 140),
        ];
        let scene = build_scene_from_sources(&sources, 0.0);
        let non_primary = scene
            .iter()
            .filter(|n| n.label != AOA_NODE_LABEL && !n.label.contains("ticker"))
            .collect::<Vec<_>>();

        for (i, a) in non_primary.iter().enumerate() {
            for b in non_primary.iter().skip(i + 1) {
                if (a.position.z - b.position.z).abs() > 0.16 {
                    continue;
                }
                let x_overlap = (a.scale.x + b.scale.x) * 0.5 - (a.position.x - b.position.x).abs();
                let y_overlap = (a.scale.y + b.scale.y) * 0.5 - (a.position.y - b.position.y).abs();
                assert!(
                    x_overlap <= 0.02 || y_overlap <= 0.02,
                    "{} and {} are clustered in the same z-layer",
                    a.label,
                    b.label
                );
            }
        }
    }

    #[test]
    fn overflow_sources_stay_in_side_shelves_not_floor_band() {
        let sources = vec![
            ("camera-brio-operator", 0.8f32, 5i32, 1280u32, 720u32),
            ("camera-c920-overhead", 0.8, 5, 1280, 720),
            ("ward-a", 0.7, 3, 420, 140),
            ("ward-b", 0.7, 3, 420, 140),
            ("ward-c", 0.7, 3, 420, 140),
            ("ward-d", 0.7, 3, 420, 140),
            ("ward-e", 0.7, 3, 420, 140),
            ("ward-f", 0.7, 3, 420, 140),
            ("ward-g", 0.7, 3, 420, 140),
        ];
        let scene = build_scene_from_sources(&sources, 0.0);
        let overflow = scene.iter().find(|n| n.label == "ward-g");
        if let Some(node) = overflow {
            let dist = node.position.distance(AOA_CENTROID);
            assert!(
                dist > UTAMA_RADIUS,
                "overflow wards must be outside Utama zone"
            );
        }
    }

    #[test]
    fn node_drift_never_modulates_opacity_or_scale() {
        let sources = vec![
            ("camera-brio-operator", 0.8f32, 5i32, 1280u32, 720u32),
            ("camera-c920-overhead", 0.8, 5, 1280, 720),
            ("programme_history", 0.7, 3, 440, 140),
        ];
        let at_start = build_scene_from_sources(&sources, 0.0);
        let later = build_scene_from_sources(&sources, 240.0);

        for start in at_start {
            let after = later.iter().find(|n| n.label == start.label).unwrap();
            assert_eq!(
                after.opacity, start.opacity,
                "opacity drift on {}",
                start.label
            );
            assert_eq!(after.scale, start.scale, "scale drift on {}", start.label);
        }
    }
}
