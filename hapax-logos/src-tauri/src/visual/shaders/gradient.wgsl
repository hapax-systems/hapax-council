// Fullscreen Oklch gradient field — L0 technique
// Driven by ambient_params: warmth, brightness, speed, turbulence

// Include oklch conversions (wgpu doesn't have #include, so these are inlined)
const PI: f32 = 3.14159265358979;

fn oklch_to_oklab(L: f32, C: f32, h_deg: f32) -> vec3<f32> {
    let h = h_deg * PI / 180.0;
    return vec3<f32>(L, C * cos(h), C * sin(h));
}

fn oklab_to_linear_srgb(lab: vec3<f32>) -> vec3<f32> {
    let l_ = lab.x + 0.3963377774 * lab.y + 0.2158037573 * lab.z;
    let m_ = lab.x - 0.1055613458 * lab.y - 0.0638541728 * lab.z;
    let s_ = lab.x - 0.0894841775 * lab.y - 1.2914855480 * lab.z;

    let l = l_ * l_ * l_;
    let m = m_ * m_ * m_;
    let s = s_ * s_ * s_;

    return vec3<f32>(
         4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    );
}

fn oklch_to_linear(L: f32, C: f32, h: f32) -> vec3<f32> {
    return oklab_to_linear_srgb(oklch_to_oklab(L, C, h));
}

fn linear_to_srgb_f(c: f32) -> f32 {
    if c <= 0.0031308 {
        return 12.92 * c;
    }
    return 1.055 * pow(c, 1.0 / 2.4) - 0.055;
}

fn linear_to_srgb(c: vec3<f32>) -> vec3<f32> {
    return vec3<f32>(
        linear_to_srgb_f(c.x),
        linear_to_srgb_f(c.y),
        linear_to_srgb_f(c.z),
    );
}

// --- Noise (ported from ambient_fbm.frag) ---

fn hash22(p: vec2<f32>) -> f32 {
    return fract(sin(dot(p, vec2<f32>(127.1, 311.7))) * 43758.5453123);
}

fn noise2(p: vec2<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    let u = f * f * (3.0 - 2.0 * f);
    return mix(
        mix(hash22(i + vec2<f32>(0.0, 0.0)), hash22(i + vec2<f32>(1.0, 0.0)), u.x),
        mix(hash22(i + vec2<f32>(0.0, 1.0)), hash22(i + vec2<f32>(1.0, 1.0)), u.x),
        u.y,
    );
}

fn fbm(p: vec2<f32>, octaves: i32) -> f32 {
    var value = 0.0;
    var amplitude = 0.5;
    var frequency = 1.0;
    var pos = p;
    for (var i = 0; i < 6; i++) {
        if i >= octaves { break; }
        value += amplitude * noise2(pos * frequency);
        frequency *= 2.0;
        amplitude *= 0.5;
    }
    return value;
}

// --- Pipeline ---

struct Uniforms {
    time: f32,
    speed: f32,
    turbulence: f32,
    color_warmth: f32,
    brightness: f32,
    _pad0: f32,
    _pad1: f32,
    _pad2: f32,
}

@group(0) @binding(0) var<uniform> u: Uniforms;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
}

// Fullscreen triangle (3 vertices, no vertex buffer needed)
@vertex
fn vs_main(@builtin(vertex_index) idx: u32) -> VertexOutput {
    var out: VertexOutput;
    // Cover screen with one triangle: vertices at (-1,-1), (3,-1), (-1,3)
    let x = f32(i32(idx & 1u)) * 4.0 - 1.0;
    let y = f32(i32(idx >> 1u)) * 4.0 - 1.0;
    out.position = vec4<f32>(x, y, 0.0, 1.0);
    out.uv = vec2<f32>((x + 1.0) * 0.5, (1.0 - y) * 0.5);
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let uv = in.uv;
    let speed = max(u.speed, 0.01);
    let t = u.time * speed * 0.3;
    let turb = max(u.turbulence, 0.05);
    let octaves = i32(2.0 + turb * 4.0);

    // Flow field
    let flow_uv = uv * 3.0 + vec2<f32>(t * 0.7, t * 0.5);
    let flow = fbm(flow_uv, octaves);
    let flow2 = fbm(flow_uv + vec2<f32>(5.2, 1.3) + t * 0.2, octaves);

    // Noise luminance
    let lum = (flow * 0.6 + flow2 * 0.4) * u.brightness;

    // Oklch color mapping (calibrated for linear→sRGB pipeline):
    // warmth 0.0 → teal (h=180, C=0.06, L=0.35)
    // warmth 1.0 → warm red (h=25, C=0.12, L=0.50)
    let base_L = mix(0.35, 0.50, u.color_warmth) + lum * 0.25;
    let base_C = mix(0.06, 0.12, u.color_warmth) + lum * 0.04;
    let base_h = mix(180.0, 25.0, u.color_warmth);

    // Spatial variation in hue
    let hue_var = (flow - 0.5) * 20.0;

    let color = oklch_to_linear(
        clamp(base_L, 0.0, 1.0),
        clamp(base_C, 0.0, 0.3),
        base_h + hue_var,
    );

    // Output linear RGB — the Rgba8UnormSrgb render target handles the
    // linear→sRGB encoding automatically on store.
    return vec4<f32>(clamp(color, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0);
}
