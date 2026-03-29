struct Params {
    u_time: f32,
    u_width: f32,
    u_height: f32,
    u_dot_size: f32,
    u_color_mode: f32,
}

struct FragmentOutput {
    @location(0) fragColor: vec4<f32>,
}

var<private> fragColor: vec4<f32>;
var<private> v_texcoord_1: vec2<f32>;
@group(0) @binding(0) 
var tex: texture_2d<f32>;
@group(0) @binding(1) 
var tex_sampler: sampler;
@group(1) @binding(0) 
var<uniform> global: Params;
var<private> gl_FragCoord_1: vec4<f32>;

fn halftone_dot(pixel: vec2<f32>, angle_deg: f32, ink: f32) -> f32 {
    var pixel_1: vec2<f32>;
    var angle_deg_1: f32;
    var ink_1: f32;
    var a: f32;
    var ca: f32;
    var sa: f32;
    var rotated: vec2<f32>;
    var cell: vec2<f32>;
    var dist: f32;
    var radius: f32;

    pixel_1 = pixel;
    angle_deg_1 = angle_deg;
    ink_1 = ink;
    let _e20 = angle_deg_1;
    a = ((_e20 * 3.14159f) / 180f);
    let _e26 = a;
    ca = cos(_e26);
    let _e29 = a;
    sa = sin(_e29);
    let _e32 = ca;
    let _e33 = pixel_1;
    let _e36 = sa;
    let _e37 = pixel_1;
    let _e41 = sa;
    let _e43 = pixel_1;
    let _e46 = ca;
    let _e47 = pixel_1;
    rotated = vec2<f32>(((_e32 * _e33.x) + (_e36 * _e37.y)), ((-(_e41) * _e43.x) + (_e46 * _e47.y)));
    let _e53 = rotated;
    let _e54 = global.u_dot_size;
    let _e55 = vec2(_e54);
    let _e60 = global.u_dot_size;
    cell = (((_e53 - (floor((_e53 / _e55)) * _e55)) / vec2(_e60)) - vec2(0.5f));
    let _e67 = cell;
    dist = length(_e67);
    let _e70 = ink_1;
    radius = (_e70 * 0.7f);
    let _e74 = dist;
    let _e75 = radius;
    return step(_e74, _e75);
}

fn main_1() {
    var uv: vec2<f32>;
    var src: vec4<f32>;
    var pixel_2: vec2<f32>;
    var lum: f32;
    var ink_2: f32;
    var d: f32;
    var c_ink: f32;
    var m_ink: f32;
    var y_ink: f32;
    var k_ink: f32;
    var c_dot: f32;
    var m_dot: f32;
    var y_dot: f32;
    var k_dot: f32;
    var color: vec3<f32> = vec3(1f);

    let _e14 = v_texcoord_1;
    uv = _e14;
    let _e16 = global.u_dot_size;
    if (_e16 < 1f) {
        {
            let _e19 = uv;
            let _e20 = textureSample(tex, tex_sampler, _e19);
            fragColor = _e20;
            return;
        }
    }
    let _e21 = uv;
    let _e22 = textureSample(tex, tex_sampler, _e21);
    src = _e22;
    let _e25 = gl_FragCoord_1;
    pixel_2 = _e25.xy;
    let _e28 = global.u_color_mode;
    if (_e28 < 0.5f) {
        {
            let _e31 = src;
            lum = dot(_e31.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
            let _e40 = lum;
            ink_2 = (1f - _e40);
            let _e43 = pixel_2;
            let _e45 = ink_2;
            let _e46 = halftone_dot(_e43, 45f, _e45);
            d = _e46;
            let _e49 = d;
            let _e51 = vec3((1f - _e49));
            fragColor = vec4<f32>(_e51.x, _e51.y, _e51.z, 1f);
            return;
        }
    } else {
        {
            let _e58 = src;
            c_ink = (1f - _e58.x);
            let _e63 = src;
            m_ink = (1f - _e63.y);
            let _e68 = src;
            y_ink = (1f - _e68.z);
            let _e72 = c_ink;
            let _e73 = m_ink;
            let _e74 = y_ink;
            k_ink = min(_e72, min(_e73, _e74));
            let _e78 = c_ink;
            let _e79 = k_ink;
            let _e82 = k_ink;
            c_ink = ((_e78 - _e79) / ((1f - _e82) + 0.001f));
            let _e87 = m_ink;
            let _e88 = k_ink;
            let _e91 = k_ink;
            m_ink = ((_e87 - _e88) / ((1f - _e91) + 0.001f));
            let _e96 = y_ink;
            let _e97 = k_ink;
            let _e100 = k_ink;
            y_ink = ((_e96 - _e97) / ((1f - _e100) + 0.001f));
            let _e105 = pixel_2;
            let _e107 = c_ink;
            let _e108 = halftone_dot(_e105, 15f, _e107);
            c_dot = _e108;
            let _e110 = pixel_2;
            let _e112 = m_ink;
            let _e113 = halftone_dot(_e110, 75f, _e112);
            m_dot = _e113;
            let _e115 = pixel_2;
            let _e117 = y_ink;
            let _e118 = halftone_dot(_e115, 0f, _e117);
            y_dot = _e118;
            let _e120 = pixel_2;
            let _e122 = k_ink;
            let _e123 = halftone_dot(_e120, 45f, _e122);
            k_dot = _e123;
            let _e129 = color;
            let _e131 = c_dot;
            color.x = (_e129.x - _e131);
            let _e134 = color;
            let _e136 = m_dot;
            color.y = (_e134.y - _e136);
            let _e139 = color;
            let _e141 = y_dot;
            color.z = (_e139.z - _e141);
            let _e143 = color;
            let _e144 = k_dot;
            color = (_e143 - vec3(_e144));
            let _e147 = color;
            let _e152 = clamp(_e147, vec3(0f), vec3(1f));
            fragColor = vec4<f32>(_e152.x, _e152.y, _e152.z, 1f);
            return;
        }
    }
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>, @builtin(position) gl_FragCoord: vec4<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    gl_FragCoord_1 = gl_FragCoord;
    main_1();
    let _e23 = fragColor;
    return FragmentOutput(_e23);
}
