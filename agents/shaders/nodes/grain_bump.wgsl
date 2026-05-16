// Grain bump shader. Modulates intensity via uniforms.custom[4].x
// (Homage coupling payload) while remaining source-bound.

struct Params {
    u_strength: f32,
}

@group(1) @binding(0)
var tex: texture_2d<f32>;
@group(1) @binding(1)
var tex_sampler: sampler;

@group(2) @binding(0)
var<uniform> global: Params;

fn surface_presence(color: vec4<f32>) -> f32 {
    let luma = dot(color.rgb, vec3<f32>(0.299, 0.587, 0.114));
    return smoothstep(0.035, 0.12, max(luma, color.a));
}

@fragment
fn main(@location(0) uv: vec2<f32>) -> @location(0) vec4<f32> {
    let source_color = textureSample(tex, tex_sampler, uv);
    
    // Homage Phase 6 coupling payload:
    // custom[4].x = active_transition_energy
    // custom[4].y = palette_accent_hue_deg
    // custom[4].z = signature_artefact_intensity
    // custom[4].w = rotation_phase
    let ward_energy = uniforms.custom[4].x;
    let presence = surface_presence(source_color);
    
    // Generate simple pseudo-random noise based on uv and time
    let noise_scale = 100.0;
    let n = fract(sin(dot(uv * noise_scale + uniforms.time, vec2<f32>(12.9898, 78.233))) * 43758.5453);
    
    // Convert noise to grain centered around 0
    let grain = (n - 0.5) * 2.0;
    
    // Bump effect: scale the grain by the ward_energy
    let bump_magnitude = 0.16 * global.u_strength * ward_energy * presence;
    
    // Apply grain bump to luminance
    var final_color = source_color.rgb + vec3<f32>(grain * bump_magnitude);
    
    // Clamp and output
    return vec4<f32>(clamp(final_color, vec3<f32>(0.0), vec3<f32>(1.0)), source_color.a);
}
