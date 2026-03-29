//! Dynamic shader graph executor.
//!
//! Replaces hardcoded techniques + compositor + postprocess with a generic pipeline
//! that reads execution plans from `/dev/shm/hapax-imagination/pipeline/plan.json`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use notify::{Event, EventKind, RecommendedWatcher, Watcher};
use serde::Deserialize;
use wgpu::util::DeviceExt;

use crate::content_textures::ContentTextureManager;
use crate::output::ShmOutput;
use crate::state::StateReader;
use crate::uniform_buffer::UniformBuffer;

const PLAN_DIR: &str = "/dev/shm/hapax-imagination/pipeline";
const PLAN_FILE: &str = "/dev/shm/hapax-imagination/pipeline/plan.json";
const UNIFORMS_JSON: &str = "/dev/shm/hapax-imagination/pipeline/uniforms.json";
const SHARED_UNIFORMS_WGSL: &str = include_str!("shaders/uniforms.wgsl");
const SHARED_VERTEX_WGSL: &str = include_str!("shaders/fullscreen_quad.wgsl");
const TEXTURE_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;

// --- Plan JSON schema ---

#[derive(Debug, Deserialize)]
struct PlanFile {
    #[serde(default)]
    passes: Vec<PlanPass>,
}

#[derive(Debug, Deserialize)]
struct PlanPass {
    node_id: String,
    shader: String,
    #[serde(default)]
    inputs: Vec<String>,
    #[serde(default = "default_output")]
    output: String,
    #[serde(default = "default_steps")]
    steps_per_frame: u32,
    /// Pass type from Python: "render" or "compute"
    #[serde(rename = "type", default)]
    pass_type: String,
    #[serde(default, deserialize_with = "deserialize_numeric_only")]
    uniforms: HashMap<String, f64>,
    #[serde(default)]
    param_order: Vec<String>,
}

fn default_output() -> String {
    "final".into()
}

fn default_steps() -> u32 {
    1
}

/// Deserialize a JSON object into HashMap<String, f64>, silently skipping non-numeric values.
fn deserialize_numeric_only<'de, D>(deserializer: D) -> Result<HashMap<String, f64>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let raw: HashMap<String, serde_json::Value> = HashMap::deserialize(deserializer)?;
    Ok(raw
        .into_iter()
        .filter_map(|(k, v)| v.as_f64().map(|n| (k, n)))
        .collect())
}

// --- Uniforms JSON override ---
// The Python modulator writes a flat dict: {"node.param": val, "signal.key": val}
// We parse as HashMap and route signal.* to shared uniforms, node.* to per-pass params.
type UniformsOverride = HashMap<String, f64>;

// --- Pipeline types ---

/// A single pass in the dynamic pipeline.
struct DynamicPass {
    node_id: String,
    render_pipeline: Option<wgpu::RenderPipeline>,
    compute_pipeline: Option<wgpu::ComputePipeline>,
    uniform_bind_group: Option<wgpu::BindGroup>,
    input_bind_group_layout: Option<wgpu::BindGroupLayout>,
    #[allow(dead_code)]
    params_buffer: Option<wgpu::Buffer>,
    params_bind_group: Option<wgpu::BindGroup>,
    inputs: Vec<String>,
    output: String,
    steps_per_frame: u32,
}

/// Named texture in the texture pool.
struct PoolTexture {
    texture: wgpu::Texture,
    view: wgpu::TextureView,
}

pub struct DynamicPipeline {
    passes: Vec<DynamicPass>,
    textures: HashMap<String, PoolTexture>,
    temporal_textures: HashMap<String, PoolTexture>,
    uniform_buffer: UniformBuffer,
    shm_output: ShmOutput,
    pending_reload: Arc<AtomicBool>,
    _watcher: RecommendedWatcher,
    plan_dir: PathBuf,
    vertex_module: wgpu::ShaderModule,
    sampler: wgpu::Sampler,
    input_bind_group_layouts: HashMap<usize, wgpu::BindGroupLayout>,
    blit_pipeline: wgpu::RenderPipeline,
    blit_bind_group_layout: wgpu::BindGroupLayout,
    params_bind_group: wgpu::BindGroup,
    params_bind_group_layout: wgpu::BindGroupLayout,
    #[allow(dead_code)]
    surface_format: wgpu::TextureFormat,
    width: u32,
    height: u32,
    frame_count: u64,
}

impl DynamicPipeline {
    pub fn new(device: &wgpu::Device, _queue: &wgpu::Queue, width: u32, height: u32, surface_format: wgpu::TextureFormat) -> Self {
        let uniform_buffer = UniformBuffer::new(device);
        let shm_output = ShmOutput::new(device, width, height);

        // Compile shared vertex module (vertex + uniforms combined)
        let vertex_source = format!("{}\n{}", SHARED_UNIFORMS_WGSL, SHARED_VERTEX_WGSL);
        let vertex_module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("fullscreen_quad vertex"),
            source: wgpu::ShaderSource::Wgsl(vertex_source.into()),
        });

        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("dynamic pipeline sampler"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });

        // Blit pipeline: copies a texture to the surface
        let blit_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("blit bgl"),
                entries: &[
                    wgpu::BindGroupLayoutEntry {
                        binding: 0,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Texture {
                            sample_type: wgpu::TextureSampleType::Float { filterable: true },
                            view_dimension: wgpu::TextureViewDimension::D2,
                            multisampled: false,
                        },
                        count: None,
                    },
                    wgpu::BindGroupLayoutEntry {
                        binding: 1,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                        count: None,
                    },
                ],
            });

        let blit_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("blit shader"),
            source: wgpu::ShaderSource::Wgsl(BLIT_WGSL.into()),
        });

        let blit_pipeline_layout =
            device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                label: Some("blit pipeline layout"),
                bind_group_layouts: &[&blit_bind_group_layout],
                push_constant_ranges: &[],
            });

        let blit_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("blit pipeline"),
            layout: Some(&blit_pipeline_layout),
            vertex: wgpu::VertexState {
                module: &blit_shader,
                entry_point: Some("vs_main"),
                buffers: &[],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &blit_shader,
                entry_point: Some("main"),
                targets: &[Some(wgpu::ColorTargetState {
                    format: surface_format,
                    blend: Some(wgpu::BlendState::REPLACE),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                ..Default::default()
            },
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
            cache: None,
        });

        // File watcher
        let pending = Arc::new(AtomicBool::new(false));
        let pending_clone = pending.clone();

        let mut watcher =
            notify::recommended_watcher(move |res: Result<Event, notify::Error>| {
                if let Ok(event) = res {
                    if matches!(event.kind, EventKind::Modify(_) | EventKind::Create(_)) {
                        pending_clone.store(true, Ordering::Relaxed);
                    }
                }
            })
            .expect("failed to create file watcher");

        // Watch plan directory (may not exist yet)
        let plan_dir = PathBuf::from(PLAN_DIR);
        std::fs::create_dir_all(&plan_dir).ok();
        watcher
            .watch(&plan_dir, notify::RecursiveMode::NonRecursive)
            .ok();

        // Dummy per-node params UBO (group 2) — 256 bytes of zeros
        let params_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("per-node params"),
            contents: &[0u8; 256],
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let params_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("per-node params layout"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        });
        let params_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("per-node params bg"),
            layout: &params_bgl,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: params_buffer.as_entire_binding(),
            }],
        });

        let mut pipeline = Self {
            passes: Vec::new(),
            textures: HashMap::new(),
            temporal_textures: HashMap::new(),
            uniform_buffer,
            shm_output,
            pending_reload: pending,
            _watcher: watcher,
            plan_dir,
            vertex_module,
            sampler,
            input_bind_group_layouts: HashMap::new(),
            blit_pipeline,
            blit_bind_group_layout,
            params_bind_group,
            params_bind_group_layout: params_bgl,
            surface_format,
            width,
            height,
            frame_count: 0,
        };

        // Try loading existing plan
        if Path::new(PLAN_FILE).exists() {
            pipeline.pending_reload.store(true, Ordering::Relaxed);
            pipeline.try_reload(device);
        }

        // Ensure "final" texture exists even with no plan
        pipeline.ensure_texture(device, "final");

        pipeline
    }

    /// Check for pending plan changes and reload if needed. Returns true if reloaded.
    pub fn try_reload(&mut self, device: &wgpu::Device) -> bool {
        if !self.pending_reload.swap(false, Ordering::Relaxed) {
            return false;
        }

        let plan_data = match std::fs::read_to_string(PLAN_FILE) {
            Ok(data) => data,
            Err(e) => {
                log::warn!("dynamic_pipeline: failed to read plan.json: {}", e);
                return false;
            }
        };

        let plan: PlanFile = match serde_json::from_str(&plan_data) {
            Ok(p) => p,
            Err(e) => {
                log::warn!("dynamic_pipeline: failed to parse plan.json: {}", e);
                return false;
            }
        };

        if plan.passes.is_empty() {
            self.passes.clear();
            log::info!("dynamic_pipeline: loaded empty plan (renders black)");
            return true;
        }

        // Collect all texture names referenced in the plan
        let mut texture_names: Vec<String> = Vec::new();
        for pass in &plan.passes {
            for input in &pass.inputs {
                if !texture_names.contains(input) {
                    texture_names.push(input.clone());
                }
            }
            if !texture_names.contains(&pass.output) {
                texture_names.push(pass.output.clone());
            }
        }

        // Ensure all textures exist in the pool
        for name in &texture_names {
            self.ensure_texture(device, name);
        }

        // Build passes
        let mut new_passes = Vec::new();
        let mut input_layouts = HashMap::new();

        for plan_pass in &plan.passes {
            let shader_path = self.plan_dir.join(&plan_pass.shader);
            let fragment_source = match std::fs::read_to_string(&shader_path) {
                Ok(src) => src,
                Err(e) => {
                    log::warn!(
                        "dynamic_pipeline: failed to read shader {:?}: {}",
                        shader_path,
                        e
                    );
                    continue;
                }
            };

            let input_count = plan_pass.inputs.len();

            if plan_pass.pass_type == "compute" {
                // Compute pass
                let compute_source = format!("{}\n{}", SHARED_UNIFORMS_WGSL, fragment_source);
                let compute_module =
                    device.create_shader_module(wgpu::ShaderModuleDescriptor {
                        label: Some(&plan_pass.node_id),
                        source: wgpu::ShaderSource::Wgsl(compute_source.into()),
                    });

                let input_bgl = Self::get_or_create_input_layout(device, input_count, &plan_pass.inputs, &mut input_layouts);
                let storage_bgl = Self::create_storage_texture_layout(device);

                let pipeline_layout =
                    device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                        label: Some(&format!("{} layout", plan_pass.node_id)),
                        bind_group_layouts: &[
                            &self.uniform_buffer.bind_group_layout,
                            &input_bgl,
                            &storage_bgl,
                        ],
                        push_constant_ranges: &[],
                    });

                let compute_pipeline =
                    device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                        label: Some(&plan_pass.node_id),
                        layout: Some(&pipeline_layout),
                        module: &compute_module,
                        entry_point: Some("cs_main"),
                        compilation_options: Default::default(),
                        cache: None,
                    });

                new_passes.push(DynamicPass {
                    node_id: plan_pass.node_id.clone(),
                    render_pipeline: None,
                    compute_pipeline: Some(compute_pipeline),
                    uniform_bind_group: None,
                    input_bind_group_layout: None,
                    params_buffer: None,
                    params_bind_group: None,
                    inputs: plan_pass.inputs.clone(),
                    output: plan_pass.output.clone(),
                    steps_per_frame: plan_pass.steps_per_frame,
                });
            } else {
                // Render pass
                let combined_source = format!("{}\n{}", SHARED_UNIFORMS_WGSL, fragment_source);
                let fragment_module =
                    device.create_shader_module(wgpu::ShaderModuleDescriptor {
                        label: Some(&plan_pass.node_id),
                        source: wgpu::ShaderSource::Wgsl(combined_source.into()),
                    });

                let input_bgl = Self::get_or_create_input_layout(device, input_count, &plan_pass.inputs, &mut input_layouts);

                // Conditionally include group 2 (per-node params) only if shader has scalar uniforms
                let has_params = !plan_pass.param_order.is_empty();
                let pipeline_layout = if has_params {
                    device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                        label: Some(&format!("{} layout", plan_pass.node_id)),
                        bind_group_layouts: &[
                            &self.uniform_buffer.bind_group_layout,
                            &input_bgl,
                            &self.params_bind_group_layout,
                        ],
                        push_constant_ranges: &[],
                    })
                } else {
                    device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                        label: Some(&format!("{} layout", plan_pass.node_id)),
                        bind_group_layouts: &[
                            &self.uniform_buffer.bind_group_layout,
                            &input_bgl,
                        ],
                        push_constant_ranges: &[],
                    })
                };
                let render_pipeline =
                    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                        label: Some(&plan_pass.node_id),
                        layout: Some(&pipeline_layout),
                        vertex: wgpu::VertexState {
                            module: &self.vertex_module,
                            entry_point: Some("vs_main"),
                            buffers: &[],
                            compilation_options: Default::default(),
                        },
                        fragment: Some(wgpu::FragmentState {
                            module: &fragment_module,
                            entry_point: Some("main"),
                            targets: &[Some(wgpu::ColorTargetState {
                                format: TEXTURE_FORMAT,
                                blend: Some(wgpu::BlendState::REPLACE),
                                write_mask: wgpu::ColorWrites::ALL,
                            })],
                            compilation_options: Default::default(),
                        }),
                        primitive: wgpu::PrimitiveState {
                            topology: wgpu::PrimitiveTopology::TriangleList,
                            ..Default::default()
                        },
                        depth_stencil: None,
                        multisample: wgpu::MultisampleState::default(),
                        multiview: None,
                        cache: None,
                    });

                // Create per-node params buffer if shader has scalar uniforms
                let (pbuf, pbg) = if has_params {
                    let mut data: Vec<f32> = Vec::new();
                    for name in &plan_pass.param_order {
                        let val = plan_pass.uniforms.get(name).copied().unwrap_or(0.0) as f32;
                        data.push(val);
                    }
                    while data.len() < 4 { data.push(0.0); }
                    while (data.len() * 4) % 16 != 0 { data.push(0.0); }

                    let buf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                        label: Some(&format!("{} params", plan_pass.node_id)),
                        contents: bytemuck::cast_slice(&data),
                        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                    });
                    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
                        label: Some(&format!("{} params bg", plan_pass.node_id)),
                        layout: &self.params_bind_group_layout,
                        entries: &[wgpu::BindGroupEntry {
                            binding: 0,
                            resource: buf.as_entire_binding(),
                        }],
                    });
                    (Some(buf), Some(bg))
                } else {
                    (None, None)
                };

                new_passes.push(DynamicPass {
                    node_id: plan_pass.node_id.clone(),
                    render_pipeline: Some(render_pipeline),
                    compute_pipeline: None,
                    uniform_bind_group: None,
                    input_bind_group_layout: None,
                    params_buffer: pbuf,
                    params_bind_group: pbg,
                    inputs: plan_pass.inputs.clone(),
                    output: plan_pass.output.clone(),
                    steps_per_frame: plan_pass.steps_per_frame,
                });
            }
        }

        self.input_bind_group_layouts = input_layouts;
        let count = new_passes.len();
        self.passes = new_passes;
        log::info!("dynamic_pipeline: loaded {} passes", count);
        true
    }

    /// Render a frame: reload if pending, build uniforms, execute passes, blit to surface, shm output.
    pub fn render(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        surface_view: &wgpu::TextureView,
        _surface_format: wgpu::TextureFormat,
        state_reader: &StateReader,
        dt: f32,
        time: f32,
        content_slot_opacities: [f32; 4],
        content_textures: Option<&ContentTextureManager>,
    ) {
        self.try_reload(device);

        // Build uniform data from state
        let mut uniform_data =
            UniformBuffer::from_state(state_reader, time, dt, self.width, self.height);

        uniform_data.slot_opacities = content_slot_opacities;

        // Apply uniforms.json signal overrides (flat dict from Python modulator)
        // Format: {"signal.key": val, "node.param": val}
        if let Ok(data) = std::fs::read_to_string(UNIFORMS_JSON) {
            if let Ok(overrides) = serde_json::from_str::<UniformsOverride>(&data) {
                for (key, &val) in &overrides {
                    if let Some(signal) = key.strip_prefix("signal.") {
                        let v = val as f32;
                        match signal {
                            "color_warmth" => uniform_data.color_warmth = v,
                            "speed" => uniform_data.speed = v,
                            "turbulence" => uniform_data.turbulence = v,
                            "brightness" => uniform_data.brightness = v,
                            "intensity" => uniform_data.intensity = v,
                            "tension" => uniform_data.tension = v,
                            "depth" => uniform_data.depth = v,
                            "coherence" => uniform_data.coherence = v,
                            "spectral_color" => uniform_data.spectral_color = v,
                            "temporal_distortion" => uniform_data.temporal_distortion = v,
                            "degradation" => uniform_data.degradation = v,
                            "pitch_displacement" => uniform_data.pitch_displacement = v,
                            "formant_character" => uniform_data.formant_character = v,
                            _ => {}
                        }
                    }
                    // node.param keys handled per-pass via params buffers at reload time
                }
            }
        }

        self.uniform_buffer.update(queue, &uniform_data);

        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("dynamic pipeline"),
        });

        if self.passes.is_empty() {
            // No plan: clear to black
            {
                let _pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("clear"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: surface_view,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                            store: wgpu::StoreOp::Store,
                        },
                    })],
                    depth_stencil_attachment: None,
                    ..Default::default()
                });
            }
            queue.submit(std::iter::once(encoder.finish()));
            return;
        }

        // If any pass references @live but no external source populates it,
        // fill it with a procedural gradient so shaders have visible input.
        // Without this, @live resolves to a black texture and the entire
        // pipeline produces near-black output.
        let needs_live = self.passes.iter().any(|p| p.inputs.iter().any(|i| i == "@live"));
        if needs_live {
            self.ensure_texture(device, "@live");
            if let Some(live_tex) = self.textures.get("@live") {
                let w = self.width as usize;
                let h = self.height as usize;
                let mut pixels = vec![0u8; w * h * 4];
                let t = time;

                // Simple hash-based noise (cheaper than proper FBM but visually rich)
                #[inline]
                fn hash(x: f32, y: f32) -> f32 {
                    let h = (x * 127.1 + y * 311.7).sin() * 43758.547;
                    h - h.floor()
                }
                #[inline]
                fn noise(x: f32, y: f32) -> f32 {
                    let ix = x.floor();
                    let iy = y.floor();
                    let fx = x - ix;
                    let fy = y - iy;
                    let sx = fx * fx * (3.0 - 2.0 * fx);
                    let sy = fy * fy * (3.0 - 2.0 * fy);
                    let a = hash(ix, iy);
                    let b = hash(ix + 1.0, iy);
                    let c = hash(ix, iy + 1.0);
                    let d = hash(ix + 1.0, iy + 1.0);
                    a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy
                }
                fn fbm(mut x: f32, mut y: f32, octaves: u32) -> f32 {
                    let mut v = 0.0f32;
                    let mut a = 0.5f32;
                    for _ in 0..octaves {
                        v += a * noise(x, y);
                        x = x * 2.0 + 100.0;
                        y = y * 2.0 + 100.0;
                        a *= 0.5;
                    }
                    v
                }

                for y in 0..h {
                    for x in 0..w {
                        let u = x as f32 / w as f32 * 4.0;
                        let v = y as f32 / h as f32 * 3.0;
                        let n1 = fbm(u + t * 0.05, v + t * 0.03, 5);
                        let n2 = fbm(u * 1.5 + t * 0.02 + 50.0, v * 1.5 - t * 0.04, 4);
                        let n3 = fbm(u * 0.8 - t * 0.01, v * 0.8 + t * 0.06 + 100.0, 4);
                        // Bright source — downstream shaders apply brightness*0.5 + dual
                        // vignette that attenuate ~4x. Need headroom to survive the chain.
                        let r = (n1 * 1.5 + n2 * 0.8 + 0.2).clamp(0.0, 1.0);
                        let g = (n2 * 1.2 + n3 * 0.6 + 0.15).clamp(0.0, 1.0);
                        let b_val = (n3 * 1.3 + n1 * 0.5 + 0.1).clamp(0.0, 1.0);
                        let idx = (y * w + x) * 4;
                        pixels[idx] = (r * 255.0) as u8;
                        pixels[idx + 1] = (g * 255.0) as u8;
                        pixels[idx + 2] = (b_val * 255.0) as u8;
                        pixels[idx + 3] = 255;
                    }
                }
                queue.write_texture(
                    wgpu::TexelCopyTextureInfo {
                        texture: &live_tex.texture,
                        mip_level: 0,
                        origin: wgpu::Origin3d::ZERO,
                        aspect: wgpu::TextureAspect::All,
                    },
                    &pixels,
                    wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some((w * 4) as u32),
                        rows_per_image: Some(h as u32),
                    },
                    wgpu::Extent3d {
                        width: self.width,
                        height: self.height,
                        depth_or_array_layers: 1,
                    },
                );
            }
        }

        // Execute each pass
        for pass in &self.passes {
            let is_temporal = pass.inputs.iter().any(|n| n.starts_with("@accum_"));

            if let Some(ref render_pipeline) = pass.render_pipeline {
                let input_bind_group = self.create_input_bind_group(device, &pass.inputs, content_textures);

                // Resolve output texture view
                let output_view = match self.textures.get(&pass.output) {
                    Some(tex) => &tex.view,
                    None => continue,
                };

                {
                    let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                        label: Some(&pass.node_id),
                        color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                            view: output_view,
                            resolve_target: None,
                            ops: wgpu::Operations {
                                load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                                store: wgpu::StoreOp::Store,
                            },
                        })],
                        depth_stencil_attachment: None,
                        ..Default::default()
                    });

                    rpass.set_pipeline(render_pipeline);
                    rpass.set_bind_group(0, &self.uniform_buffer.bind_group, &[]);
                    rpass.set_bind_group(1, &input_bind_group, &[]);
                    if let Some(ref pbg) = pass.params_bind_group {
                        rpass.set_bind_group(2, pbg, &[]);
                    }
                    rpass.draw(0..3, 0..1);
                } // render pass dropped here

                // Copy output to temporal buffer for next frame's feedback
                if is_temporal {
                    if let (Some(src), Some(dst)) = (
                        self.textures.get(&pass.output),
                        self.temporal_textures.get(&pass.node_id),
                    ) {
                        let copy_size = wgpu::Extent3d {
                            width: self.width,
                            height: self.height,
                            depth_or_array_layers: 1,
                        };
                        encoder.copy_texture_to_texture(
                            src.texture.as_image_copy(),
                            dst.texture.as_image_copy(),
                            copy_size,
                        );
                    }
                }
            } else if let Some(ref compute_pipeline) = pass.compute_pipeline {
                let input_bind_group = self.create_input_bind_group(device, &pass.inputs, content_textures);
                let storage_bind_group =
                    self.create_storage_bind_group(device, &pass.output);

                let workgroups_x = (self.width + 7) / 8;
                let workgroups_y = (self.height + 7) / 8;

                for _ in 0..pass.steps_per_frame {
                    let mut cpass =
                        encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                            label: Some(&pass.node_id),
                            timestamp_writes: None,
                        });

                    cpass.set_pipeline(compute_pipeline);
                    cpass.set_bind_group(0, &self.uniform_buffer.bind_group, &[]);
                    cpass.set_bind_group(1, &input_bind_group, &[]);
                    cpass.set_bind_group(2, &storage_bind_group, &[]);
                    cpass.dispatch_workgroups(workgroups_x, workgroups_y, 1);
                }
            }
        }

        // Blit final texture to surface
        if let Some(final_tex) = self.textures.get("final") {
            let blit_bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("blit bind group"),
                layout: &self.blit_bind_group_layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: wgpu::BindingResource::TextureView(&final_tex.view),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::Sampler(&self.sampler),
                    },
                ],
            });

            // The blit pipeline was created with TEXTURE_FORMAT but we need to render to the
            // actual surface format. Create an ad-hoc blit pass that targets surface_view.
            // For now, use a simple render pass with the existing blit pipeline if formats match,
            // otherwise clear black as fallback.
            let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("blit to surface"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: surface_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                ..Default::default()
            });

            // The blit pipeline targets TEXTURE_FORMAT which should match surface sRGB
            rpass.set_pipeline(&self.blit_pipeline);
            rpass.set_bind_group(0, &blit_bg, &[]);
            rpass.draw(0..3, 0..1);
        }

        // Copy final texture to SHM output (every other frame to save bandwidth)
        if self.frame_count % 2 == 0 {
            if let Some(final_tex) = self.textures.get("final") {
                self.shm_output
                    .copy_to_staging(&mut encoder, &final_tex.texture);
            }
        }

        queue.submit(std::iter::once(encoder.finish()));

        // Write SHM frame (every other frame)
        if self.frame_count % 2 == 0 {
            self.shm_output.write_frame(device);
        }

        self.frame_count += 1;
    }

    pub fn resize(&mut self, device: &wgpu::Device, width: u32, height: u32) {
        self.width = width;
        self.height = height;

        // Recreate all pool textures at new size
        let names: Vec<String> = self.textures.keys().cloned().collect();
        for name in names {
            self.textures.remove(&name);
            self.ensure_texture(device, &name);
        }

        // Recreate temporal textures at new size
        let temporal_names: Vec<String> = self.temporal_textures.keys().cloned().collect();
        for name in temporal_names {
            self.temporal_textures.remove(&name);
            self.ensure_temporal_texture(device, &name);
        }

        self.shm_output.resize(device, width, height);
    }

    // --- Internal helpers ---

    fn ensure_texture(&mut self, device: &wgpu::Device, name: &str) {
        if self.textures.contains_key(name) {
            return;
        }

        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(name),
            size: wgpu::Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEXTURE_FORMAT,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::RENDER_ATTACHMENT
                | wgpu::TextureUsages::COPY_SRC
                | wgpu::TextureUsages::COPY_DST
                | wgpu::TextureUsages::STORAGE_BINDING,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        self.textures.insert(name.to_string(), PoolTexture { texture, view });
    }

    fn ensure_temporal_texture(&mut self, device: &wgpu::Device, node_id: &str) {
        if self.temporal_textures.contains_key(node_id) {
            return;
        }
        let label = format!("temporal_{}", node_id);
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(&label),
            size: wgpu::Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEXTURE_FORMAT,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        self.temporal_textures.insert(node_id.to_string(), PoolTexture { texture, view });
    }

    fn get_or_create_input_layout(
        device: &wgpu::Device,
        input_count: usize,
        input_names: &[String],
        layouts: &mut HashMap<usize, wgpu::BindGroupLayout>,
    ) -> wgpu::BindGroupLayout {
        let has_content_slots = input_names.iter().any(|n| n.starts_with("content_slot_"));
        if !has_content_slots {
            if !layouts.contains_key(&input_count) {
                layouts.insert(input_count, Self::create_input_layout(device, input_count));
            }
        }
        // Always create a fresh one to return — wgpu layouts are not Clone,
        // but two layouts created with the same descriptor are compatible.
        Self::create_input_layout_for(device, input_count, input_names)
    }

    fn create_input_layout(device: &wgpu::Device, input_count: usize) -> wgpu::BindGroupLayout {
        Self::create_input_layout_for(device, input_count, &[])
    }

    /// Create a bind group layout for group 1 inputs.
    ///
    /// Standard inputs get alternating texture/sampler pairs.
    /// Inputs named `content_slot_*` are bare textures sharing the first sampler
    /// (matches the content_layer.wgsl hand-written binding layout).
    fn create_input_layout_for(
        device: &wgpu::Device,
        input_count: usize,
        input_names: &[String],
    ) -> wgpu::BindGroupLayout {
        let has_content_slots = input_names.iter().any(|n| n.starts_with("content_slot_"));

        if has_content_slots {
            // content_layer layout: binding 0=tex, 1=sampler, 2..N=bare textures
            let mut entries = vec![
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
            ];
            let slot_count = input_names.iter().filter(|n| n.starts_with("content_slot_")).count();
            for i in 0..slot_count {
                entries.push(wgpu::BindGroupLayoutEntry {
                    binding: (2 + i) as u32,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                });
            }
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("content_layer input bgl"),
                entries: &entries,
            })
        } else {
            // Standard: alternating texture/sampler pairs
            let mut entries: Vec<wgpu::BindGroupLayoutEntry> = Vec::new();
            let count = input_count.max(1);
            for i in 0..count {
                entries.push(wgpu::BindGroupLayoutEntry {
                    binding: (i * 2) as u32,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                });
                entries.push(wgpu::BindGroupLayoutEntry {
                    binding: (i * 2 + 1) as u32,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                });
            }
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("dynamic input bgl"),
                entries: &entries,
            })
        }
    }

    fn create_storage_texture_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
        device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("storage texture bgl"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::COMPUTE,
                ty: wgpu::BindingType::StorageTexture {
                    access: wgpu::StorageTextureAccess::WriteOnly,
                    format: TEXTURE_FORMAT,
                    view_dimension: wgpu::TextureViewDimension::D2,
                },
                count: None,
            }],
        })
    }

    fn create_input_bind_group(
        &self,
        device: &wgpu::Device,
        inputs: &[String],
        content_textures: Option<&ContentTextureManager>,
    ) -> wgpu::BindGroup {
        let input_count = inputs.len();
        let has_content_slots = inputs.iter().any(|n| n.starts_with("content_slot_"));

        // Use cached layout from reload — fall back to fresh creation if uncached
        let owned_layout;
        let layout = if has_content_slots {
            owned_layout = Self::create_input_layout_for(device, input_count, inputs);
            &owned_layout
        } else {
            match self.input_bind_group_layouts.get(&input_count) {
                Some(cached) => cached,
                None => {
                    owned_layout = Self::create_input_layout(device, input_count);
                    &owned_layout
                }
            }
        };

        let mut entries: Vec<wgpu::BindGroupEntry> = Vec::new();

        if has_content_slots {
            // content_layer layout: binding 0=tex, 1=sampler, 2..N=bare content textures
            // First input is the pipeline texture (non-content-slot)
            let pipeline_inputs: Vec<_> = inputs.iter().filter(|n| !n.starts_with("content_slot_")).collect();
            let content_inputs: Vec<_> = inputs.iter().filter(|n| n.starts_with("content_slot_")).collect();

            // Binding 0: pipeline input texture
            let view = if let Some(name) = pipeline_inputs.first() {
                self.textures.get(name.as_str())
                    .or_else(|| self.textures.get("final"))
                    .map(|t| &t.view)
                    .unwrap()
            } else {
                self.textures.values().next().map(|t| &t.view).unwrap()
            };
            entries.push(wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(view),
            });
            // Binding 1: shared sampler
            entries.push(wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::Sampler(&self.sampler),
            });
            // Binding 2..N: content slot textures
            for (i, name) in content_inputs.iter().enumerate() {
                let idx: usize = name.strip_prefix("content_slot_")
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(0);
                let slot_view = content_textures
                    .map(|ct| ct.slot_view(idx))
                    .unwrap_or_else(|| self.textures.get("final").map(|t| &t.view).unwrap());
                entries.push(wgpu::BindGroupEntry {
                    binding: (2 + i) as u32,
                    resource: wgpu::BindingResource::TextureView(slot_view),
                });
            }
        } else {
            // Standard: alternating texture/sampler pairs
            for (i, name) in inputs.iter().enumerate() {
                let view = if let Some(node_id) = name.strip_prefix("@accum_") {
                    // Temporal accumulation input — use feedback buffer
                    self.temporal_textures.get(node_id)
                        .or_else(|| self.textures.get("final"))
                        .map(|t| &t.view)
                        .unwrap()
                } else {
                    self.textures.get(name.as_str())
                        .or_else(|| self.textures.get("final"))
                        .map(|t| &t.view)
                        .unwrap()
                };
                entries.push(wgpu::BindGroupEntry {
                    binding: (i * 2) as u32,
                    resource: wgpu::BindingResource::TextureView(view),
                });
                entries.push(wgpu::BindGroupEntry {
                    binding: (i * 2 + 1) as u32,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                });
            }
        }
        // If no inputs, still provide a default texture+sampler (shaders expect at least one)
        if inputs.is_empty() {
            if let Some(tex) = self.textures.values().next() {
                entries.push(wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&tex.view),
                });
                entries.push(wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                });
            }
        }

        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("dynamic input bg"),
            layout,
            entries: &entries,
        })
    }

    fn create_storage_bind_group(
        &self,
        device: &wgpu::Device,
        output_name: &str,
    ) -> wgpu::BindGroup {
        let layout = Self::create_storage_texture_layout(device);

        let view = if let Some(tex) = self.textures.get(output_name) {
            &tex.view
        } else {
            &self.textures.get("final").unwrap().view
        };

        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("storage bg"),
            layout: &layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(view),
            }],
        })
    }
}

/// Inline blit shader: samples a texture and outputs it.
const BLIT_WGSL: &str = r#"
struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vertex_index: u32) -> VertexOutput {
    var out: VertexOutput;
    let x = f32(i32(vertex_index & 1u) * 2 - 1);
    let y = f32(i32(vertex_index >> 1u) * 2 - 1);
    out.position = vec4<f32>(x, y, 0.0, 1.0);
    out.uv = vec2<f32>((x + 1.0) * 0.5, (1.0 - y) * 0.5);
    return out;
}

@group(0) @binding(0)
var source_texture: texture_2d<f32>;
@group(0) @binding(1)
var source_sampler: sampler;

@fragment
fn main(in: VertexOutput) -> @location(0) vec4<f32> {
    return textureSample(source_texture, source_sampler, in.uv);
}
"#;
