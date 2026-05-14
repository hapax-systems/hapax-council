//! Scene graph for 3D compositor proof of concept (Phase 0).
//!
//! A flat list of `SceneNode` structs, each representing a textured quad
//! at a position in 3D space. No tree hierarchy needed for Phase 0.
//!
//! Z-plane mapping translates the Python `z_plane_constants.py` semantic
//! depth categories into real Z positions:
//!
//! | Plane           | Python float | Real Z  |
//! |-----------------|-------------|---------|
//! | beyond-scrim    | 0.2         | -8.0    |
//! | mid-scrim       | 0.5         | -5.0    |
//! | on-scrim        | 0.9         | -3.0    |
//! | surface-scrim   | 1.0         | -2.0    |

use glam::{Mat4, Quat, Vec3};

/// Semantic depth planes matching `z_plane_constants.py`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ZPlane {
    BeyondScrim,
    MidScrim,
    OnScrim,
    SurfaceScrim,
}

impl ZPlane {
    /// Map to real Z position in world space (right-handed, -Z is into screen).
    pub fn z_position(self) -> f32 {
        match self {
            ZPlane::BeyondScrim => -8.0,
            ZPlane::MidScrim => -5.0,
            ZPlane::OnScrim => -3.0,
            ZPlane::SurfaceScrim => -2.0,
        }
    }

    /// The original Python float value for parity checks.
    pub fn python_float(self) -> f32 {
        match self {
            ZPlane::BeyondScrim => 0.2,
            ZPlane::MidScrim => 0.5,
            ZPlane::OnScrim => 0.9,
            ZPlane::SurfaceScrim => 1.0,
        }
    }
}

/// A node in the scene graph — a textured quad in 3D space.
#[derive(Debug, Clone)]
pub struct SceneNode {
    pub label: String,
    pub position: Vec3,
    pub rotation: Quat,
    pub scale: Vec3,
    pub z_plane: ZPlane,
    /// Index into ContentSourceManager or a fixed texture binding.
    /// None means use the placeholder texture.
    pub content_source_index: Option<usize>,
    pub opacity: f32,
}

impl SceneNode {
    pub fn new(label: &str, z_plane: ZPlane) -> Self {
        Self {
            label: label.to_string(),
            position: Vec3::new(0.0, 0.0, z_plane.z_position()),
            rotation: Quat::IDENTITY,
            scale: Vec3::ONE,
            z_plane,
            content_source_index: None,
            opacity: 1.0,
        }
    }

    /// Compute the model matrix from position, rotation, and scale.
    pub fn model_matrix(&self) -> Mat4 {
        Mat4::from_scale_rotation_translation(self.scale, self.rotation, self.position)
    }
}

/// Build the Phase 0 proof scene: 5 quads at different depths.
pub fn build_proof_scene() -> Vec<SceneNode> {
    let mut nodes = Vec::new();

    // Ward quad at beyond-scrim (deepest — behind everything)
    let mut ward_deep = SceneNode::new("ward-beyond", ZPlane::BeyondScrim);
    ward_deep.scale = Vec3::new(3.0, 2.0, 1.0);
    ward_deep.opacity = 0.6;
    nodes.push(ward_deep);

    // Ward quad at mid-scrim
    let mut ward_mid = SceneNode::new("ward-mid", ZPlane::MidScrim);
    ward_mid.position.x = 1.5;
    ward_mid.scale = Vec3::new(2.5, 1.8, 1.0);
    ward_mid.opacity = 0.8;
    nodes.push(ward_mid);

    // Ward quad at on-scrim (legibility plane)
    let mut ward_legible = SceneNode::new("ward-on-scrim", ZPlane::OnScrim);
    ward_legible.position.x = -1.0;
    ward_legible.scale = Vec3::new(2.0, 1.5, 1.0);
    nodes.push(ward_legible);

    // Camera quad at surface-scrim (closest)
    let mut camera = SceneNode::new("camera-surface", ZPlane::SurfaceScrim);
    camera.content_source_index = Some(0);
    camera.scale = Vec3::new(1.6, 0.9, 1.0);
    nodes.push(camera);

    // Sierpinski placeholder at mid-scrim
    let mut sierpinski = SceneNode::new("sierpinski-placeholder", ZPlane::MidScrim);
    sierpinski.position.x = -0.5;
    sierpinski.position.y = 0.3;
    sierpinski.scale = Vec3::new(2.0, 2.0, 1.0);
    sierpinski.opacity = 0.7;
    nodes.push(sierpinski);

    nodes
}

/// Perspective camera parameters.
#[derive(Debug, Clone)]
pub struct Camera3D {
    pub eye: Vec3,
    pub center: Vec3,
    pub up: Vec3,
    pub fov_y_radians: f32,
    pub aspect_ratio: f32,
    pub near: f32,
    pub far: f32,
}

impl Camera3D {
    pub fn new(width: u32, height: u32) -> Self {
        Self {
            eye: Vec3::new(0.0, 0.0, 2.0),
            center: Vec3::new(0.0, 0.0, -5.0),
            up: Vec3::Y,
            fov_y_radians: 60.0_f32.to_radians(),
            aspect_ratio: width as f32 / height as f32,
            near: 0.1,
            far: 100.0,
        }
    }

    pub fn view_matrix(&self) -> Mat4 {
        Mat4::look_at_rh(self.eye, self.center, self.up)
    }

    pub fn projection_matrix(&self) -> Mat4 {
        Mat4::perspective_rh(self.fov_y_radians, self.aspect_ratio, self.near, self.far)
    }

    /// Slow orbital drift for demonstrating parallax. Period ~30s.
    pub fn apply_orbital_drift(&mut self, time: f32) {
        let radius = 0.8;
        let speed = std::f32::consts::TAU / 30.0; // 30-second period
        self.eye.x = radius * (time * speed).sin();
        self.eye.y = 0.3 * (time * speed * 0.7).sin();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn z_plane_mapping_matches_python_constants() {
        assert_eq!(ZPlane::BeyondScrim.python_float(), 0.2);
        assert_eq!(ZPlane::MidScrim.python_float(), 0.5);
        assert_eq!(ZPlane::OnScrim.python_float(), 0.9);
        assert_eq!(ZPlane::SurfaceScrim.python_float(), 1.0);
    }

    #[test]
    fn z_positions_are_ordered_by_depth() {
        // More negative = farther from camera (right-handed convention)
        assert!(ZPlane::BeyondScrim.z_position() < ZPlane::MidScrim.z_position());
        assert!(ZPlane::MidScrim.z_position() < ZPlane::OnScrim.z_position());
        assert!(ZPlane::OnScrim.z_position() < ZPlane::SurfaceScrim.z_position());
    }

    #[test]
    fn model_matrix_identity_at_origin() {
        let node = SceneNode {
            label: "test".to_string(),
            position: Vec3::ZERO,
            rotation: Quat::IDENTITY,
            scale: Vec3::ONE,
            z_plane: ZPlane::OnScrim,
            content_source_index: None,
            opacity: 1.0,
        };
        let m = node.model_matrix();
        assert_eq!(m, Mat4::IDENTITY);
    }

    #[test]
    fn model_matrix_includes_position() {
        let node = SceneNode::new("test", ZPlane::BeyondScrim);
        let m = node.model_matrix();
        // Translation should appear in column 3
        let col3 = m.col(3);
        assert!((col3.z - (-8.0)).abs() < 1e-5);
    }

    #[test]
    fn camera_projection_is_finite() {
        let cam = Camera3D::new(1920, 1080);
        let proj = cam.projection_matrix();
        for col in 0..4 {
            for row in 0..4 {
                assert!(proj.col(col)[row].is_finite(),
                    "projection[{col}][{row}] is not finite");
            }
        }
    }

    #[test]
    fn camera_view_is_finite() {
        let cam = Camera3D::new(1920, 1080);
        let view = cam.view_matrix();
        for col in 0..4 {
            for row in 0..4 {
                assert!(view.col(col)[row].is_finite(),
                    "view[{col}][{row}] is not finite");
            }
        }
    }

    #[test]
    fn proof_scene_has_five_nodes() {
        let scene = build_proof_scene();
        assert_eq!(scene.len(), 5);
    }

    #[test]
    fn orbital_drift_stays_bounded() {
        let mut cam = Camera3D::new(1920, 1080);
        for t in (0..600).map(|i| i as f32 * 0.1) {
            cam.apply_orbital_drift(t);
            assert!(cam.eye.x.abs() <= 1.0, "x out of bounds at t={t}");
            assert!(cam.eye.y.abs() <= 0.5, "y out of bounds at t={t}");
        }
    }

    #[test]
    fn ndc_depth_ordering() {
        // Points at different Z planes should produce different NDC depths,
        // with farther points having larger NDC z (in [0,1] range for wgpu).
        let cam = Camera3D::new(1920, 1080);
        let vp = cam.projection_matrix() * cam.view_matrix();

        let near_point = vp * glam::Vec4::new(0.0, 0.0, ZPlane::SurfaceScrim.z_position(), 1.0);
        let far_point = vp * glam::Vec4::new(0.0, 0.0, ZPlane::BeyondScrim.z_position(), 1.0);

        let near_ndc_z = near_point.z / near_point.w;
        let far_ndc_z = far_point.z / far_point.w;

        // In wgpu (reverse-Z or standard), farther objects should have
        // different NDC z than nearer objects.
        assert!((near_ndc_z - far_ndc_z).abs() > 0.01,
            "NDC depth should differ: near={near_ndc_z}, far={far_ndc_z}");
    }
}
