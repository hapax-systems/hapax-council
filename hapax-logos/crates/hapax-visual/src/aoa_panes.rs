//! Aperture of Apertures pane registry.
//!
//! This module is the Rust-side authority for AoA pane identity. The WGSL
//! shader still renders the panes, but it should mirror this lineage/ordinal
//! contract rather than being the only place where pane identity exists.

use glam::Vec3;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

pub const AOA_OBJECT_ID: &str = "aoa-pyramid";
pub const AOA_GEOMETRY_REVISION: &str = "aoa-tetrix-v1";
pub const AOA_PANE_SCHEMA_VERSION: u32 = 1;
pub const AOA_PANE_ID_VERSION: &str = "v1";
pub const AOA_TETRIX_RENDER_DEPTH: u32 = 2;

pub const AOA_ROOT_MODEL_VERTICES: [[f32; 3]; 4] = [
    [-0.58, -0.44, 0.34],
    [0.58, -0.44, 0.34],
    [0.0, 0.60, 0.34],
    [0.0, -0.095, -0.62],
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

pub fn aoa_leaf_tetrahedron_count(depth: u32) -> usize {
    4usize.pow(depth)
}

pub fn aoa_total_tetrahedron_count(depth: u32) -> usize {
    (0..=depth).map(aoa_leaf_tetrahedron_count).sum()
}

pub fn aoa_raw_edge_segment_count(depth: u32) -> usize {
    aoa_total_tetrahedron_count(depth) * 6
}

pub fn aoa_raw_triangular_pane_count(depth: u32) -> usize {
    aoa_total_tetrahedron_count(depth) * 4
}

pub fn aoa_pane_start_ordinal(depth: u32) -> u32 {
    4 * (4u32.pow(depth) - 1) / 3
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

pub fn aoa_pane_records(render_depth: u32) -> Vec<AoaPaneRecord> {
    let mut records = Vec::with_capacity(aoa_raw_triangular_pane_count(render_depth));
    for depth in 0..=render_depth {
        for tetra_index in 0..aoa_leaf_tetrahedron_count(depth) as u32 {
            let lineage = aoa_lineage_from_tetra_index(depth, tetra_index);
            for face_index in 0..4 {
                let face_key = AoaFaceKey::from_index(face_index).expect("face index is 0..4");
                records.push(aoa_pane_record(&lineage, face_key));
            }
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
    let max_density = match (depth, boundary_role) {
        (0, _) => AoaMaxDensity::Text,
        (1, AoaBoundaryRole::HullSubface) => AoaMaxDensity::CompactData,
        (1, _) => AoaMaxDensity::Glyph,
        _ => AoaMaxDensity::Accent,
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tetrix_count_formulas_match_active_shader_depth() {
        assert_eq!(AOA_TETRIX_RENDER_DEPTH, 2);
        assert_eq!(aoa_leaf_tetrahedron_count(0), 1);
        assert_eq!(aoa_leaf_tetrahedron_count(1), 4);
        assert_eq!(aoa_leaf_tetrahedron_count(2), 16);
        assert_eq!(aoa_total_tetrahedron_count(2), 21);
        assert_eq!(aoa_raw_edge_segment_count(2), 126);
        assert_eq!(aoa_raw_triangular_pane_count(2), 84);
    }

    #[test]
    fn lineage_and_ordinal_formula_match_shader_order() {
        let lineage = vec![AoaChild::A, AoaChild::D];
        assert_eq!(aoa_tetra_index(&lineage), 3);
        assert_eq!(aoa_pane_start_ordinal(2), 20);
        assert_eq!(aoa_pane_ordinal(&lineage, AoaFaceKey::Bcd), 33);
        assert_eq!(
            aoa_pane_id(&lineage, AoaFaceKey::Bcd),
            "aoa:pane:v1:a.d:bcd"
        );
        assert_eq!(aoa_lineage_from_tetra_index(2, 3), lineage);
    }

    #[test]
    fn active_manifest_has_all_depth_two_panes_with_unique_identity() {
        let manifest = aoa_active_pane_manifest();
        assert_eq!(manifest.render_depth, AOA_TETRIX_RENDER_DEPTH);
        assert_eq!(manifest.pane_count, 84);
        assert_eq!(manifest.panes.len(), 84);
        assert!(aoa_manifest_has_unique_identity(&manifest));
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

        assert_eq!(pane.pane_ordinal, 33);
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
    fn manifest_records_are_json_serializable() {
        let manifest = aoa_pane_manifest(1);
        let json = serde_json::to_string(&manifest).expect("manifest should serialize");
        assert!(json.contains("aoa:pane:v1:r:abd"));
        assert!(json.contains("aoa-tetrix-v1"));
    }
}
