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
            orbit_radius: 0.8,
        }
    }

    pub fn view_matrix(&self) -> Mat4 {
        Mat4::look_at_rh(self.eye, self.target, self.up)
    }

    pub fn projection_matrix(&self) -> Mat4 {
        Mat4::perspective_rh(self.fov_y_radians, self.aspect, self.near, self.far)
    }

    /// Gentle orbital drift — camera traces an ellipse over 45s.
    /// Called once per frame with wall-clock time.
    pub fn apply_orbital_drift(&mut self, time: f32) {
        let period = 45.0;
        let angle = (time / period) * std::f32::consts::TAU;
        let dx = self.orbit_radius * angle.cos();
        let dy = self.orbit_radius * 0.5 * (angle * 0.7).sin();
        self.eye.x = dx;
        self.eye.y = dy;
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
/// The layout is intentionally concrete: Sierpinski occupies the central
/// foreground, camera feeds form an exploded cube on the left, IR/CBIP feeds
/// extend that cube upward, and system wards form a matching cube on the
/// right. Secondary panels occupy a middle-depth band. Drift is spatial only:
/// it never modulates source opacity or scale.
pub fn build_scene_from_sources(
    active_sources: &[(&str, f32, i32, u32, u32)], // (id, opacity, z_order, width, height)
    time: f32,
) -> Vec<SceneNode> {
    let mut nodes = Vec::new();

    let mut used_indices = Vec::new();

    if push_optional_node(
        &mut nodes,
        active_sources,
        "sierpinski-lines",
        Vec3::new(0.0, 0.35, ZPlane::SurfaceScrim.z_position() - 0.4),
        3.35,
        0.92,
        0.0,
    ) {
        if let Some((idx, _)) = active_sources
            .iter()
            .enumerate()
            .find(|(_, (id, _, _, _, _))| *id == "sierpinski-lines")
        {
            used_indices.push(idx);
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
            Vec3::new(0.0, -1.62, ZPlane::SurfaceScrim.z_position() - 0.18),
            if ticker_id == "grounding_provenance_ticker" {
                0.36
            } else {
                0.48
            },
            0.86,
            0.0,
        ) {
            if let Some((idx, _)) = active_sources
                .iter()
                .enumerate()
                .find(|(_, (id, _, _, _, _))| *id == ticker_id)
            {
                used_indices.push(idx);
            }
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

    push_exploded_cube(
        &mut nodes,
        active_sources,
        &hls_indices,
        Vec3::new(-3.55, -0.05, ZPlane::OnScrim.z_position() + 0.18),
        1.15,
        1.55,
    );
    push_exploded_cube(
        &mut nodes,
        active_sources,
        &ir_indices,
        Vec3::new(-3.45, 1.62, ZPlane::MidScrim.z_position() + 1.18),
        0.82,
        1.15,
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
    push_exploded_cube(
        &mut nodes,
        active_sources,
        &right_cube,
        Vec3::new(3.55, -0.03, ZPlane::OnScrim.z_position() + 0.14),
        0.92,
        1.35,
    );

    let mid_band = source_indices_except(active_sources, &used_indices);
    let mid_z = ZPlane::MidScrim.z_position() - 0.25;
    for (local_idx, src_idx) in mid_band.iter().take(10).enumerate() {
        let col = local_idx % 5;
        let row = local_idx / 5;
        let x = (col as f32 - 2.0) * 1.25;
        let y = 1.08 - row as f32 * 0.88;
        nodes.push(make_node(
            active_sources,
            *src_idx,
            Vec3::new(x, y, mid_z + 0.46 - row as f32 * 0.22),
            0.58,
            0.42,
            0.0,
        ));
    }

    let mut far_excluded = used_indices.clone();
    far_excluded.extend(mid_band.iter().take(10).copied());
    let far_band = source_indices_except(active_sources, &far_excluded);
    for (local_idx, src_idx) in far_band.iter().take(12).enumerate() {
        let col = local_idx % 6;
        let row = local_idx / 6;
        let x = (col as f32 - 2.5) * 1.35;
        let y = -2.0 - row as f32 * 0.52;
        nodes.push(make_node(
            active_sources,
            *src_idx,
            Vec3::new(x, y, ZPlane::BeyondScrim.z_position() + 1.1),
            0.42,
            0.26,
            0.0,
        ));
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
            assert!(cam.eye.x.abs() < 1.0, "x out of bounds at t={t}");
            assert!(cam.eye.y.abs() < 1.0, "y out of bounds at t={t}");
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

        // With only two cameras, the remaining content starts the right-hand cube.
        let content = scene
            .iter()
            .find(|n| n.label == "content-episodic_recall")
            .unwrap();
        assert!(
            content.position.x > 3.0,
            "content should start the right cube"
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

        let ticker = scene
            .iter()
            .find(|n| n.label == "grounding_provenance_ticker")
            .unwrap();
        assert!(ticker.position.y < sierpinski.position.y);

        let hls = scene
            .iter()
            .find(|n| n.label == "camera-brio-operator")
            .unwrap();
        assert!(hls.position.x < -3.0, "HLS cube should sit left");

        let ir = scene
            .iter()
            .find(|n| n.label == "camera-pi-noir-desk")
            .unwrap();
        assert!(ir.position.x < -3.0 && ir.position.y > hls.position.y);

        let ward = scene
            .iter()
            .find(|n| n.label == "programme_history")
            .unwrap();
        assert!(ward.position.x > 3.0, "ward cube should sit right");
    }

    #[test]
    fn mid_band_accepts_overflow_without_occlusion() {
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
            (overflow.position.z - (ZPlane::MidScrim.z_position() + 0.21)).abs() < 0.01,
            "overflow wards should enter the shifted-forward mid-level band"
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
