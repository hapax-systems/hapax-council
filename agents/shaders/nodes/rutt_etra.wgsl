struct Params {
    u_displacement: f32,
    u_line_density: f32,
    u_line_width: f32,
    u_color_mode: f32,
}

struct FragmentOutput {
    @location(0) fragColor: vec4<f32>,
}

var<private> fragColor: vec4<f32>;
var<private> v_texcoord_1: vec2<f32>;
@group(1) @binding(0) 
var tex: texture_2d<f32>;
@group(1) @binding(1) 
var tex_sampler: sampler;
@group(2) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var uv: vec2<f32>;
    var color: vec4<f32>;
    var lum: f32;
    var linePos: f32;
    var line: f32;
    var displaced_y: f32;
    var dispColor: vec4<f32>;
    var dispLum: f32;
    var result: vec3<f32>;

    let _e14 = v_texcoord_1;
    uv = _e14;
    let _e16 = uv;
    let _e17 = textureSample(tex, tex_sampler, _e16);
    color = _e17;
    let _e19 = color;
    lum = dot(_e19.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e27 = uv;

    let _e30 = (_e27.y * uniforms.resolution.y);
    let _e31 = global.u_line_density;
    linePos = (_e30 - (floor((_e30 / _e31)) * _e31));
    let _e37 = global.u_line_density;
    let _e38 = global.u_line_width;
    let _e40 = linePos;
    line = step((_e37 - _e38), _e40);
    let _e43 = uv;
    let _e45 = lum;
    let _e46 = global.u_displacement;
    displaced_y = (_e43.y + ((_e45 * _e46) * 0.01f));
    let _e52 = uv;
    let _e54 = displaced_y;
    let _e59 = textureSample(tex, tex_sampler, vec2<f32>(_e52.x, clamp(_e54, 0f, 1f)));
    dispColor = _e59;
    let _e61 = dispColor;
    dispLum = dot(_e61.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e70 = global.u_color_mode;
    if (_e70 > 0.5f) {
        {
            let _e73 = dispColor;
            result = _e73.xyz;
        }
    } else {
        {
            let _e77 = dispLum;
            result = vec3(_e77);
        }
    }

    let surface_presence =         smoothstep(0.025f, 0.14f, lum);
    let displacement_strength = clamp(abs(global.u_displacement) * 0.035f, 0f, 0.65f);
    let line_strength = line * surface_presence * displacement_strength;
    let rutt_signal = mix(color.xyz, result, vec3<f32>(0.72f));
    let blended_raw = mix(color.xyz, rutt_signal, vec3<f32>(line_strength));
    let blended = max(blended_raw, color.xyz + abs(rutt_signal - color.xyz) * 0.18f * line_strength);
    fragColor = vec4<f32>(blended, color.a);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
