//! Shared GPU uniform buffer matching the WGSL Uniforms struct.

use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::state::StateReader;

/// Must match hapax-logos/crates/hapax-visual/src/shaders/uniforms.wgsl exactly.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct UniformData {
    pub time: f32,
    pub dt: f32,
    pub resolution: [f32; 2],
    // Stimmung
    pub stance: u32,
    pub color_warmth: f32,
    pub speed: f32,
    pub turbulence: f32,
    pub brightness: f32,
    // 9 expressive dimensions
    pub intensity: f32,
    pub tension: f32,
    pub depth: f32,
    pub coherence: f32,
    pub spectral_color: f32,
    pub temporal_distortion: f32,
    pub degradation: f32,
    pub pitch_displacement: f32,
    pub formant_character: f32,
    // Padding to align slot_opacities (vec4<f32>) to 16-byte boundary (std140).
    // formant_character ends at offset 72; next vec4 must start at offset 80.
    pub _align_pad: [f32; 2],
    // Content layer
    pub slot_opacities: [f32; 4],
    // Per-node custom params (32 floats packed as 8 vec4s for uniform alignment)
    pub custom: [[f32; 4]; 8],
}

impl Default for UniformData {
    fn default() -> Self {
        Self {
            time: 0.0,
            dt: 0.016,
            resolution: [1920.0, 1080.0],
            stance: 0,
            color_warmth: 0.0,
            speed: 0.08,
            turbulence: 0.1,
            brightness: 0.25,
            intensity: 0.0,
            tension: 0.0,
            depth: 0.0,
            coherence: 0.0,
            spectral_color: 0.0,
            temporal_distortion: 0.0,
            degradation: 0.0,
            pitch_displacement: 0.0,
            formant_character: 0.0,
            _align_pad: [0.0; 2],
            slot_opacities: [0.0; 4],
            custom: [[0.0; 4]; 8],
        }
    }
}

pub struct UniformBuffer {
    pub buffer: wgpu::Buffer,
    pub bind_group_layout: wgpu::BindGroupLayout,
    pub bind_group: wgpu::BindGroup,
}

impl UniformBuffer {
    pub fn new(device: &wgpu::Device) -> Self {
        let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("uniforms"),
            contents: bytemuck::bytes_of(&UniformData::default()),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let bind_group_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("uniforms_layout"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        });

        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("uniforms_bind_group"),
            layout: &bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: buffer.as_entire_binding(),
            }],
        });

        Self {
            buffer,
            bind_group_layout,
            bind_group,
        }
    }

    pub fn update(&self, queue: &wgpu::Queue, data: &UniformData) {
        queue.write_buffer(&self.buffer, 0, bytemuck::bytes_of(data));
    }

    /// Build UniformData from StateReader + frame timing.
    pub fn from_state(
        state: &StateReader,
        time: f32,
        dt: f32,
        width: u32,
        height: u32,
    ) -> UniformData {
        let s = &state.smoothed;
        let dims = &state.imagination.dimensions;

        UniformData {
            time,
            dt,
            resolution: [width as f32, height as f32],
            stance: match s.stance {
                crate::state::Stance::Nominal => 0,
                crate::state::Stance::Cautious => 1,
                crate::state::Stance::Degraded => 2,
                crate::state::Stance::Critical => 3,
            },
            color_warmth: s.color_warmth,
            speed: s.speed,
            turbulence: s.turbulence,
            brightness: s.brightness,
            intensity: *dims.get("intensity").unwrap_or(&0.0) as f32,
            tension: *dims.get("tension").unwrap_or(&0.0) as f32,
            depth: *dims.get("depth").unwrap_or(&0.0) as f32,
            coherence: *dims.get("coherence").unwrap_or(&0.0) as f32,
            spectral_color: *dims.get("spectral_color").unwrap_or(&0.0) as f32,
            temporal_distortion: *dims.get("temporal_distortion").unwrap_or(&0.0) as f32,
            degradation: *dims.get("degradation").unwrap_or(&0.0) as f32,
            pitch_displacement: *dims.get("pitch_displacement").unwrap_or(&0.0) as f32,
            formant_character: *dims.get("formant_character").unwrap_or(&0.0) as f32,
            _align_pad: [0.0; 2],
            slot_opacities: [0.0; 4], // Updated by content layer pass
            custom: [[0.0; 4]; 8],        // Updated from uniforms.json
        }
    }
}
