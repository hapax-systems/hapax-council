// Oklch ↔ linear sRGB conversion functions
// Based on Björn Ottosson's Oklab (2020)

const PI: f32 = 3.14159265358979;

// Oklch → Oklab
fn oklch_to_oklab(L: f32, C: f32, h_deg: f32) -> vec3<f32> {
    let h = h_deg * PI / 180.0;
    return vec3<f32>(L, C * cos(h), C * sin(h));
}

// Oklab → linear sRGB
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

// Oklch → linear sRGB (convenience)
fn oklch_to_linear(L: f32, C: f32, h: f32) -> vec3<f32> {
    return oklab_to_linear_srgb(oklch_to_oklab(L, C, h));
}

// linear sRGB → sRGB (gamma encode)
fn linear_to_srgb(c: f32) -> f32 {
    if c <= 0.0031308 {
        return 12.92 * c;
    }
    return 1.055 * pow(c, 1.0 / 2.4) - 0.055;
}

fn linear_to_srgb3(c: vec3<f32>) -> vec3<f32> {
    return vec3<f32>(
        linear_to_srgb(c.x),
        linear_to_srgb(c.y),
        linear_to_srgb(c.z),
    );
}
