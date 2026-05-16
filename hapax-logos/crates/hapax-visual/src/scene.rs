//! 3D scene graph for the compositor migration.
//!
//! Phase 0 introduced a static proof scene. Phase 1 replaces it with a
//! dynamic scene graph that reads from `ContentSourceManager` and maps
//! each active content source to a positioned 3D quad.

use glam::{Mat4, Vec3};

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

/// A quad in 3D space, optionally bound to a content source texture.
#[derive(Debug, Clone)]
pub struct SceneNode {
    pub label: String,
    pub position: Vec3,
    pub scale: Vec3,
    pub rotation_y: f32,
    pub opacity: f32,
    /// Index into ContentSourceManager's ordered source list.
    /// When None, the renderer uses a placeholder texture.
    pub content_source_id: Option<String>,
}

impl SceneNode {
    pub fn new(label: &str) -> Self {
        Self {
            label: label.to_string(),
            position: Vec3::ZERO,
            scale: Vec3::ONE,
            rotation_y: 0.0,
            opacity: 1.0,
            content_source_id: None,
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
            fov_y_radians: 60.0f32.to_radians(),
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

    fn orbital_pose_at(&self, time: f32) -> (Vec3, Vec3) {
        let period = 72.0;
        let angle = (time / period) * std::f32::consts::TAU;
        let lateral = angle.sin();
        let depth_dip = 1.0 - lateral * lateral;
        let eye = Vec3::new(
            self.orbit_radius * lateral,
            0.34 * (angle * 0.5).sin(),
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
    /// Called once per frame with wall-clock time.
    pub fn apply_orbital_drift(&mut self, time: f32) {
        let (eye, target) = self.orbital_pose_at(time);
        self.eye = eye;
        self.target = target;
    }

    /// Moving neon point light: same orbital path as the camera, half-speed,
    /// lifted roughly ten degrees above the eye path.
    pub fn point_light_position(&self, time: f32) -> Vec3 {
        let (eye, target) = self.orbital_pose_at(time * 0.5);
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
) {
    if columns == 0 {
        return;
    }

    for (local_idx, &src_idx) in source_indices.iter().enumerate() {
        let col = local_idx % columns;
        let row = local_idx / columns;
        let x = (col as f32 - (columns.saturating_sub(1) as f32 * 0.5)) * x_spacing;
        let y = -(row as f32) * y_spacing;
        let z = -(row as f32) * z_spacing + (col as f32 - columns as f32 * 0.5) * 0.04;
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
            "sierpinski-lines" | "grounding_provenance_ticker"
        );

        if is_primary {
            continue;
        }

        let drift_x = 0.035 * ((time * 0.09 + phase).sin() - phase.sin());
        let drift_y = 0.025 * ((time * 0.07 + phase * 0.9).cos() - (phase * 0.9).cos());
        let drift_z = 0.055 * ((time * 0.06 + phase * 1.4).sin() - (phase * 1.4).sin());
        node.position += Vec3::new(drift_x, drift_y, drift_z);

        if !node.label.starts_with("camera-") {
            node.rotation_y += 0.018 * ((time * 0.05 + phase).sin() - phase.sin());
        }
    }
}

/// Build scene nodes dynamically from active content sources.
///
/// The layout is intentionally concrete but temporary: Sierpinski occupies
/// the central foreground, while cameras, IR feeds, and wards sit on separated
/// shelves around it. The point is to exercise x/y/z depth without letting
/// any source cluster become the composition. Drift is spatial only: it never
/// modulates source opacity or scale.
pub fn build_scene_from_sources(
    active_sources: &[(&str, f32, i32, u32, u32)], // (id, opacity, z_order, width, height)
    time: f32,
) -> Vec<SceneNode> {
    let mut nodes = Vec::new();
    let primary_forward = 0.55;
    let on_ring_forward = 0.82;
    let mid_ring_forward = 1.04;
    let far_ring_forward = 1.62;

    let mut used_indices = Vec::new();
    // Full-frame/projection-capable sources can represent prior layouts or
    // broad overlays. They require an explicit role before the baseline 3D
    // layout may place them as ordinary residual quads; otherwise they read as
    // rogue scene reprojections or fake reflections.
    mark_projection_capable_sources(&mut used_indices, active_sources);

    if push_optional_node(
        &mut nodes,
        active_sources,
        "sierpinski-lines",
        Vec3::new(
            0.0,
            0.35,
            ZPlane::SurfaceScrim.z_position() - 0.4 + primary_forward,
        ),
        3.35,
        0.92,
        0.0,
    ) {
        mark_source_used(&mut used_indices, active_sources, "sierpinski-lines");
        // The base Sierpinski source is published separately for legacy
        // consumers. Do not let the default 3D scene place it again as a
        // residual low-band object when the primary Sierpinski-lines object
        // is already present. Transient re-projection belongs to explicit
        // effects, not the baseline layout.
        mark_source_used(&mut used_indices, active_sources, "sierpinski");
    } else if push_optional_node(
        &mut nodes,
        active_sources,
        "sierpinski",
        Vec3::new(
            0.0,
            0.35,
            ZPlane::SurfaceScrim.z_position() - 0.4 + primary_forward,
        ),
        3.05,
        0.74,
        0.0,
    ) {
        mark_source_used(&mut used_indices, active_sources, "sierpinski");
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

    push_deoccluded_grid(
        &mut nodes,
        active_sources,
        &hls_indices,
        Vec3::new(
            -2.36,
            0.78,
            ZPlane::OnScrim.z_position() + 0.02 + on_ring_forward,
        ),
        2,
        0.50,
        1.14,
        0.72,
        0.42,
        1.12,
    );
    push_deoccluded_grid(
        &mut nodes,
        active_sources,
        &ir_indices,
        Vec3::new(
            -2.18,
            1.58,
            ZPlane::MidScrim.z_position() + 0.86 + mid_ring_forward,
        ),
        3,
        0.36,
        0.96,
        0.46,
        0.30,
        0.98,
    );
    push_deoccluded_grid(
        &mut nodes,
        active_sources,
        &static_camera_artifact_indices,
        Vec3::new(
            1.52,
            -1.34,
            ZPlane::BeyondScrim.z_position() + 1.12 + far_ring_forward,
        ),
        2,
        0.16,
        0.42,
        0.24,
        0.18,
        0.18,
    );

    let mut remaining = source_indices_except(active_sources, &used_indices);
    remaining.sort_by(|&a, &b| {
        active_sources[b]
            .2
            .cmp(&active_sources[a].2)
            .then(a.cmp(&b))
    });
    let right_cube: Vec<usize> = remaining.iter().take(6).copied().collect();
    used_indices.extend(right_cube.iter().copied());
    push_deoccluded_grid(
        &mut nodes,
        active_sources,
        &right_cube,
        Vec3::new(
            2.30,
            0.74,
            ZPlane::OnScrim.z_position() - 0.04 + on_ring_forward,
        ),
        2,
        0.44,
        1.08,
        0.58,
        0.38,
        0.96,
    );

    let mid_band = source_indices_except(active_sources, &used_indices);
    push_deoccluded_grid(
        &mut nodes,
        active_sources,
        &mid_band.iter().take(10).copied().collect::<Vec<_>>(),
        Vec3::new(
            2.08,
            -0.84,
            ZPlane::MidScrim.z_position() + 0.48 + mid_ring_forward,
        ),
        2,
        0.24,
        0.80,
        0.35,
        0.25,
        0.32,
    );

    let mut far_excluded = used_indices.clone();
    far_excluded.extend(mid_band.iter().take(10).copied());
    let far_band = source_indices_except(active_sources, &far_excluded);
    push_deoccluded_grid(
        &mut nodes,
        active_sources,
        &far_band.iter().take(12).copied().collect::<Vec<_>>(),
        Vec3::new(
            -2.10,
            -0.92,
            ZPlane::BeyondScrim.z_position() + 1.26 + far_ring_forward,
        ),
        3,
        0.20,
        0.66,
        0.30,
        0.21,
        0.16,
    );

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

    // Sierpinski placeholder (mid-scrim, centered)
    let mut sierp = SceneNode::new("proof-sierpinski");
    sierp.position = Vec3::new(0.0, 0.5, ZPlane::MidScrim.z_position() - 0.5);
    sierp.scale = Vec3::new(2.0, 2.0, 1.0);
    sierp.opacity = 0.5;
    nodes.push(sierp);

    nodes
}

// ─── Tests ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

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
            let (half_speed_eye, _) = cam.orbital_pose_at(t * 0.5);
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

        assert_eq!(scene.len(), 3, "should have 3 nodes");

        let ids: Vec<&str> = scene.iter().map(|n| n.label.as_str()).collect();
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

        // With only two cameras, the remaining content starts the right-hand shelf.
        let content = scene
            .iter()
            .find(|n| n.label == "content-episodic_recall")
            .unwrap();
        assert!(
            content.position.x > 1.5,
            "content should start the right shelf"
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
        assert_eq!(scene.len(), 1, "invisible source should be skipped");
    }

    #[test]
    fn dynamic_scene_preserves_aspect_ratio() {
        let sources = vec![("cam", 1.0f32, 8i32, 1920u32, 1080u32)];
        let refs: Vec<(&str, f32, i32, u32, u32)> = sources
            .iter()
            .map(|&(id, op, z, w, h)| (id, op, z, w, h))
            .collect();
        let scene = build_scene_from_sources(&refs, 0.0);
        let aspect = scene[0].scale.x / scene[0].scale.y;
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
    fn requested_geometric_layout_places_primary_elements() {
        let sources = vec![
            ("sierpinski-lines", 0.9f32, 4i32, 1280u32, 720u32),
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

        let sierpinski = scene
            .iter()
            .find(|n| n.label == "sierpinski-lines")
            .unwrap();
        assert!(sierpinski.position.x.abs() < 0.01);
        assert!(sierpinski.position.y > 0.0);
        assert!(
            scene.iter().all(|n| n.label != "sierpinski"),
            "baseline layout must not re-project base Sierpinski as a residual object"
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
        assert!(ticker.position.y < sierpinski.position.y);

        let hls = scene
            .iter()
            .find(|n| n.label == "camera-brio-operator")
            .unwrap();
        assert!(hls.position.x < -2.0, "HLS shelf should sit left");

        let ir = scene
            .iter()
            .find(|n| n.label == "camera-pi-noir-desk")
            .unwrap();
        assert!(ir.position.x < -2.0 && ir.position.y > hls.position.y);

        let ward = scene
            .iter()
            .find(|n| n.label == "programme_history")
            .unwrap();
        assert!(ward.position.x > 1.5, "ward shelf should sit right");
    }

    #[test]
    fn surrounding_content_uses_depth_without_passing_sierpinski() {
        let sources = vec![
            ("sierpinski-lines", 0.9f32, 4i32, 1280u32, 720u32),
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
        let sierpinski_z = scene
            .iter()
            .find(|n| n.label == "sierpinski-lines")
            .unwrap()
            .position
            .z;

        let hls = scene
            .iter()
            .find(|n| n.label == "camera-brio-operator")
            .unwrap();
        assert!(
            hls.position.z < sierpinski_z && hls.position.z > -2.65,
            "HLS cameras should be near Sierpinski but not on the same front layer"
        );

        let ir = scene
            .iter()
            .find(|n| n.label == "camera-pi-noir-desk")
            .unwrap();
        assert!(
            ir.position.z < hls.position.z - 0.45,
            "IR row should remain a distinct upper/mid z layer"
        );

        let ward = scene
            .iter()
            .find(|n| n.label == "programme_history")
            .unwrap();
        assert!(
            ward.position.z < sierpinski_z && ward.position.z > -2.75,
            "primary wards should be near but still behind the Sierpinski anchor"
        );
    }

    #[test]
    fn static_camera_artifacts_do_not_read_as_live_camera_tiles() {
        let sources = vec![
            ("sierpinski-lines", 0.9f32, 4i32, 1280u32, 720u32),
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
            static_artifact.position.z < primary_ward.position.z - 1.5,
            "static camera-derived artifacts should sit in a rear artifact band"
        );
        assert!(
            static_artifact.opacity < live_camera.opacity * 0.35,
            "static camera-derived artifacts must not carry live-camera visual authority"
        );
        assert!(
            static_artifact.scale.y < live_camera.scale.y * 0.5,
            "static camera-derived artifacts should be materially smaller than live camera tiles"
        );
    }

    #[test]
    fn deoccluded_baseline_spreads_sources_within_each_layer() {
        let sources = vec![
            ("sierpinski-lines", 0.9f32, 4i32, 1280u32, 720u32),
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
            .filter(|n| n.label != "sierpinski-lines" && !n.label.contains("ticker"))
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
        let overflow = scene.iter().find(|n| n.label == "ward-g").unwrap();
        assert!(
            overflow.position.y > -1.45,
            "overflow wards must not become a low floor/reflection-like band"
        );
        assert!(
            overflow.position.x.abs() > 1.6,
            "overflow wards should remain in side shelves rather than a centered ghost layout"
        );
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
