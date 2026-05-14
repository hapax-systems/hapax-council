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
            opacity: 1.0,
            content_source_id: None,
        }
    }

    /// 4x4 model matrix: translate + scale (no rotation for quads).
    pub fn model_matrix(&self) -> Mat4 {
        Mat4::from_translation(self.position) * Mat4::from_scale(self.scale)
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
            orbit_radius: 0.3,
        }
    }

    pub fn view_matrix(&self) -> Mat4 {
        Mat4::look_at_rh(self.eye, self.target, self.up)
    }

    pub fn projection_matrix(&self) -> Mat4 {
        Mat4::perspective_rh(self.fov_y_radians, self.aspect, self.near, self.far)
    }

    /// Gentle orbital drift — camera traces an ellipse over 30s.
    /// Called once per frame with wall-clock time.
    pub fn apply_orbital_drift(&mut self, time: f32) {
        let period = 30.0;
        let angle = (time / period) * std::f32::consts::TAU;
        let dx = self.orbit_radius * angle.cos();
        let dy = self.orbit_radius * 0.5 * (angle * 0.7).sin();
        self.eye.x = dx;
        self.eye.y = dy;
    }
}

// ─── Dynamic scene builders ───────────────────────────────────────

/// Build scene nodes dynamically from active content sources.
///
/// Sources are grouped by z-plane and laid out in a centered grid at
/// each depth. Cameras get the foreground; wards fill the mid and
/// background layers. The camera FOV at each z-plane determines the
/// visible width, and quads are scaled and spaced to fill it without
/// overflowing off-screen.
pub fn build_scene_from_sources(
    active_sources: &[(&str, f32, i32, u32, u32)], // (id, opacity, z_order, width, height)
) -> Vec<SceneNode> {
    let mut nodes = Vec::new();

    // Group sources by z-plane
    let mut by_plane: [Vec<usize>; 4] = [vec![], vec![], vec![], vec![]];
    for (i, &(_, opacity, z_order, _, _)) in active_sources.iter().enumerate() {
        if opacity < 0.001 {
            continue;
        }
        let plane_idx = match ZPlane::from_z_order(z_order) {
            ZPlane::BeyondScrim => 0,
            ZPlane::MidScrim => 1,
            ZPlane::OnScrim => 2,
            ZPlane::SurfaceScrim => 3,
        };
        by_plane[plane_idx].push(i);
    }

    let planes = [
        ZPlane::BeyondScrim,
        ZPlane::MidScrim,
        ZPlane::OnScrim,
        ZPlane::SurfaceScrim,
    ];

    for (plane_idx, plane) in planes.iter().enumerate() {
        let indices = &by_plane[plane_idx];
        if indices.is_empty() {
            continue;
        }

        let z = plane.z_position();
        let count = indices.len();

        // Visible width at this z-depth for a 60° FOV camera at z=2.0:
        // half_width ≈ tan(30°) * |z_camera - z_plane| = 0.577 * dist
        let camera_z = 2.0_f32;
        let dist = (camera_z - z).abs();
        let visible_half_w = 0.577 * dist;
        let visible_w = visible_half_w * 2.0;

        // Quad size — scale to fit the plane, smaller when more sources
        let max_quad_h = match plane {
            ZPlane::SurfaceScrim => 2.2f32,
            ZPlane::OnScrim => 1.8f32,
            ZPlane::MidScrim => 1.5f32,
            ZPlane::BeyondScrim => 1.2f32,
        };

        // Grid layout: determine columns and rows
        let cols = ((count as f32).sqrt().ceil() as usize).max(1);
        let rows = ((count + cols - 1) / cols).max(1);

        // Spacing to fit within visible width with margin
        let margin = 0.85; // use 85% of visible width
        let cell_w = (visible_w * margin) / cols as f32;
        let cell_h = max_quad_h * 1.2;

        for (local_idx, &src_idx) in indices.iter().enumerate() {
            let (source_id, opacity, _, width, height) = active_sources[src_idx];

            let aspect = width as f32 / height.max(1) as f32;
            let quad_h = max_quad_h.min(cell_w / aspect) as f32; // fit in cell
            let quad_w = quad_h * aspect;

            let col = local_idx % cols;
            let row = local_idx / cols;

            // Center the grid
            let x = (col as f32 - (cols as f32 - 1.0) / 2.0) * cell_w;
            let y = -((row as f32 - (rows as f32 - 1.0) / 2.0) * cell_h);

            let mut node = SceneNode::new(source_id);
            node.position = Vec3::new(x, y, z);
            node.scale = Vec3::new(quad_w, quad_h, 1.0);
            node.opacity = opacity;
            node.content_source_id = Some(source_id.to_string());
            nodes.push(node);
        }
    }

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
        ward.position = Vec3::new(
            (i as f32 - 1.0) * 2.0,
            0.0,
            z_plane.z_position(),
        );
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
        let scene = build_scene_from_sources(&refs);

        assert_eq!(scene.len(), 3, "should have 3 nodes");

        // Sources are now grouped by z-plane: MidScrim (z_order=3) first,
        // then OnScrim (z_order=5). Verify all are present.
        let ids: Vec<&str> = scene.iter().map(|n| n.label.as_str()).collect();
        assert!(ids.contains(&"content-episodic_recall"), "content should be present");
        assert!(ids.contains(&"camera-brio-operator"), "camera brio should be present");
        assert!(ids.contains(&"camera-c920-overhead"), "camera c920 should be present");

        // Content node is on MidScrim
        let content = scene.iter().find(|n| n.label == "content-episodic_recall").unwrap();
        assert!(
            (content.position.z - ZPlane::MidScrim.z_position()).abs() < 0.01,
            "content should be on MidScrim"
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
        let scene = build_scene_from_sources(&refs);
        assert_eq!(scene.len(), 1, "invisible source should be skipped");
    }

    #[test]
    fn dynamic_scene_preserves_aspect_ratio() {
        let sources = vec![("cam", 1.0f32, 8i32, 1920u32, 1080u32)];
        let refs: Vec<(&str, f32, i32, u32, u32)> = sources
            .iter()
            .map(|&(id, op, z, w, h)| (id, op, z, w, h))
            .collect();
        let scene = build_scene_from_sources(&refs);
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
        let scene = build_scene_from_sources(&refs);
        // Sources grouped by z-plane: content-recall (z=3 MidScrim) before camera (z=5 OnScrim)
        assert_eq!(
            scene[0].content_source_id.as_deref(),
            Some("content-recall")
        );
        assert_eq!(
            scene[1].content_source_id.as_deref(),
            Some("camera-brio")
        );
    }
}
