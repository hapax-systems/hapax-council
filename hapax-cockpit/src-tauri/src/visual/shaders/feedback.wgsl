// Framebuffer feedback: read previous composited frame, apply Oklch decay + hue shift

struct Params {
    decay: f32,        // multiplicative decay in L channel (default: 0.97)
    hue_shift: f32,    // degrees per frame (default: 0.5)
    _pad0: f32,
    _pad1: f32,
}

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var prev_frame: texture_2d<f32>;
@group(0) @binding(2) var dst: texture_storage_2d<rgba8unorm, write>;

const PI: f32 = 3.14159265358979;

// sRGB → linear
fn srgb_to_linear_f(c: f32) -> f32 {
    if c <= 0.04045 {
        return c / 12.92;
    }
    return pow((c + 0.055) / 1.055, 2.4);
}

fn srgb_to_linear(c: vec3<f32>) -> vec3<f32> {
    return vec3<f32>(srgb_to_linear_f(c.x), srgb_to_linear_f(c.y), srgb_to_linear_f(c.z));
}

// linear → sRGB
fn linear_to_srgb_f(c: f32) -> f32 {
    if c <= 0.0031308 {
        return 12.92 * c;
    }
    return 1.055 * pow(c, 1.0 / 2.4) - 0.055;
}

fn linear_to_srgb(c: vec3<f32>) -> vec3<f32> {
    return vec3<f32>(linear_to_srgb_f(c.x), linear_to_srgb_f(c.y), linear_to_srgb_f(c.z));
}

// linear sRGB → Oklab
fn linear_to_oklab(c: vec3<f32>) -> vec3<f32> {
    let l = 0.4122214708 * c.x + 0.5363325363 * c.y + 0.0514459929 * c.z;
    let m = 0.2119034982 * c.x + 0.6806995451 * c.y + 0.1073969566 * c.z;
    let s = 0.0883024619 * c.x + 0.2817188376 * c.y + 0.6299787005 * c.z;

    let l_ = pow(max(l, 0.0), 1.0/3.0);
    let m_ = pow(max(m, 0.0), 1.0/3.0);
    let s_ = pow(max(s, 0.0), 1.0/3.0);

    return vec3<f32>(
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    );
}

// Oklab → linear sRGB
fn oklab_to_linear(lab: vec3<f32>) -> vec3<f32> {
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

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let dims = textureDimensions(prev_frame);
    if gid.x >= dims.x || gid.y >= dims.y {
        return;
    }

    let pos = vec2<i32>(gid.xy);
    let srgb = textureLoad(prev_frame, pos, 0).rgb;
    let linear = srgb_to_linear(srgb);
    var lab = linear_to_oklab(linear);

    // Decay lightness
    lab.x *= params.decay;

    // Hue shift in Oklab (rotate a,b plane)
    let h_rad = params.hue_shift * PI / 180.0;
    let cos_h = cos(h_rad);
    let sin_h = sin(h_rad);
    let new_a = lab.y * cos_h - lab.z * sin_h;
    let new_b = lab.y * sin_h + lab.z * cos_h;
    lab.y = new_a;
    lab.z = new_b;

    let result = linear_to_srgb(clamp(oklab_to_linear(lab), vec3<f32>(0.0), vec3<f32>(1.0)));
    textureStore(dst, pos, vec4<f32>(result, 1.0));
}
