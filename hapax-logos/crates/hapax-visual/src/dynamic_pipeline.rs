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
    #[serde(default)]
    compute: bool,
}

fn default_output() -> String {
    "final".into()
}

fn default_steps() -> u32 {
    1
}

// --- Uniforms JSON override ---

#[derive(Debug, Default, Deserialize)]
struct UniformsOverride {
    #[serde(default)]
    custom: Vec<f32>,
    #[serde(default)]
    slot_opacities: Option<[f32; 4]>,
}

// --- Pipeline types ---

/// A single pass in the dynamic pipeline.
struct DynamicPass {
    node_id: String,
    render_pipeline: Option<wgpu::RenderPipeline>,
    compute_pipeline: Option<wgpu::ComputePipeline>,
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
                entry_point: Some("fs_main"),
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

        let mut pipeline = Self {
            passes: Vec::new(),
            textures: HashMap::new(),
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

            if plan_pass.compute {
                // Compute pass
                let compute_source = format!("{}\n{}", SHARED_UNIFORMS_WGSL, fragment_source);
                let compute_module =
                    device.create_shader_module(wgpu::ShaderModuleDescriptor {
                        label: Some(&plan_pass.node_id),
                        source: wgpu::ShaderSource::Wgsl(compute_source.into()),
                    });

                let input_bgl = Self::get_or_create_input_layout(device, input_count, &mut input_layouts);
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

                let input_bgl = Self::get_or_create_input_layout(device, input_count, &mut input_layouts);

                let pipeline_layout =
                    device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                        label: Some(&format!("{} layout", plan_pass.node_id)),
                        bind_group_layouts: &[
                            &self.uniform_buffer.bind_group_layout,
                            &input_bgl,
                        ],
                        push_constant_ranges: &[],
                    });

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
                            entry_point: Some("fs_main"),
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

                new_passes.push(DynamicPass {
                    node_id: plan_pass.node_id.clone(),
                    render_pipeline: Some(render_pipeline),
                    compute_pipeline: None,
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
    ) {
        self.try_reload(device);

        // Build uniform data from state
        let mut uniform_data =
            UniformBuffer::from_state(state_reader, time, dt, self.width, self.height);

        // Apply uniforms.json overrides
        if let Ok(data) = std::fs::read_to_string(UNIFORMS_JSON) {
            if let Ok(overrides) = serde_json::from_str::<UniformsOverride>(&data) {
                if let Some(opacities) = overrides.slot_opacities {
                    uniform_data.slot_opacities = opacities;
                }
                for (i, &val) in overrides.custom.iter().enumerate() {
                    if i < 32 {
                        uniform_data.custom[i] = val;
                    }
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

        // Execute each pass
        for pass in &self.passes {
            if let Some(ref render_pipeline) = pass.render_pipeline {
                // Resolve input texture views
                let input_bind_group = self.create_input_bind_group(device, &pass.inputs);

                // Resolve output texture view
                let output_view = match self.textures.get(&pass.output) {
                    Some(tex) => &tex.view,
                    None => continue,
                };

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
                rpass.draw(0..3, 0..1);
            } else if let Some(ref compute_pipeline) = pass.compute_pipeline {
                let input_bind_group = self.create_input_bind_group(device, &pass.inputs);
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
                | wgpu::TextureUsages::STORAGE_BINDING,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        self.textures.insert(name.to_string(), PoolTexture { texture, view });
    }

    fn get_or_create_input_layout(
        device: &wgpu::Device,
        input_count: usize,
        layouts: &mut HashMap<usize, wgpu::BindGroupLayout>,
    ) -> wgpu::BindGroupLayout {
        if !layouts.contains_key(&input_count) {
            layouts.insert(input_count, Self::create_input_layout(device, input_count));
        }
        // Always create a fresh one to return — wgpu layouts are not Clone,
        // but two layouts created with the same descriptor are compatible.
        Self::create_input_layout(device, input_count)
    }

    fn create_input_layout(device: &wgpu::Device, input_count: usize) -> wgpu::BindGroupLayout {
        let mut entries: Vec<wgpu::BindGroupLayoutEntry> = Vec::new();

        // One texture per input
        for i in 0..input_count {
            entries.push(wgpu::BindGroupLayoutEntry {
                binding: i as u32,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            });
        }

        // Sampler at the end
        entries.push(wgpu::BindGroupLayoutEntry {
            binding: input_count as u32,
            visibility: wgpu::ShaderStages::FRAGMENT,
            ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
            count: None,
        });

        device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("dynamic input bgl"),
            entries: &entries,
        })
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
    ) -> wgpu::BindGroup {
        let input_count = inputs.len();

        // Use cached layout from reload — fall back to fresh creation if uncached
        let owned_layout;
        let layout = match self.input_bind_group_layouts.get(&input_count) {
            Some(cached) => cached,
            None => {
                owned_layout = Self::create_input_layout(device, input_count);
                &owned_layout
            }
        };

        let mut entries: Vec<wgpu::BindGroupEntry> = Vec::new();

        for (i, name) in inputs.iter().enumerate() {
            let view = self.textures.get(name)
                .or_else(|| self.textures.get("final"))
                .map(|t| &t.view)
                .unwrap();
            entries.push(wgpu::BindGroupEntry {
                binding: i as u32,
                resource: wgpu::BindingResource::TextureView(view),
            });
        }

        entries.push(wgpu::BindGroupEntry {
            binding: input_count as u32,
            resource: wgpu::BindingResource::Sampler(&self.sampler),
        });

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
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    return textureSample(source_texture, source_sampler, in.uv);
}
"#;
