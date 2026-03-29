struct Params {
    u_threshold: f32,
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
@group(0) @binding(2) 
var tex_prev: texture_2d<f32>;
@group(0) @binding(3) 
var tex_prev_sampler: sampler;
@group(1) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var cur: vec4<f32>;
    var prev: vec4<f32>;
    var d: vec3<f32>;
    var luma: f32;
    var r: vec3<f32>;
    var g: f32;
    var b: f32;

    let _e10 = v_texcoord_1;
    let _e11 = textureSample(tex, tex_sampler, _e10);
    cur = _e11;
    let _e13 = v_texcoord_1;
    let _e14 = textureSample(tex_prev, tex_prev_sampler, _e13);
    prev = _e14;
    let _e16 = cur;
    let _e18 = prev;
    d = abs((_e16.xyz - _e18.xyz));
    let _e23 = d;
    luma = dot(_e23, vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e31 = global.u_color_mode;
    if (_e31 < 0.5f) {
        {
            let _e34 = global.u_threshold;
            let _e35 = luma;
            let _e37 = luma;
            g = (step(_e34, _e35) * _e37);
            let _e40 = g;
            r = vec3(_e40);
        }
    } else {
        let _e42 = global.u_color_mode;
        if (_e42 < 1.5f) {
            {
                let _e45 = global.u_threshold;
                let _e46 = luma;
                b = step(_e45, _e46);
                let _e49 = b;
                r = vec3(_e49);
            }
        } else {
            {
                let _e51 = cur;
                let _e53 = global.u_threshold;
                let _e54 = luma;
                r = (_e51.xyz * step(_e53, _e54));
            }
        }
    }
    let _e57 = r;
    fragColor = vec4<f32>(_e57.x, _e57.y, _e57.z, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
