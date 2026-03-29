struct Params {
    u_alpha: f32,
    u_mode: f32,
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
@group(1) @binding(2) 
var tex_b: texture_2d<f32>;
@group(1) @binding(3) 
var tex_b_sampler: sampler;
@group(2) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var a: vec4<f32>;
    var b: vec4<f32>;
    var r: vec3<f32>;

    let _e10 = v_texcoord_1;
    let _e11 = textureSample(tex, tex_sampler, _e10);
    a = _e11;
    let _e13 = v_texcoord_1;
    let _e14 = textureSample(tex_b, tex_b_sampler, _e13);
    b = _e14;
    let _e17 = global.u_mode;
    if (_e17 < 0.5f) {
        let _e22 = a;
        let _e27 = b;
        r = (vec3(1f) - ((vec3(1f) - _e22.xyz) * (vec3(1f) - _e27.xyz)));
    } else {
        let _e34 = global.u_mode;
        if (_e34 < 1.5f) {
            let _e37 = a;
            let _e39 = b;
            r = (_e37.xyz + _e39.xyz);
        } else {
            let _e42 = global.u_mode;
            if (_e42 < 2.5f) {
                let _e45 = a;
                let _e47 = b;
                r = (_e45.xyz * _e47.xyz);
            } else {
                let _e50 = global.u_mode;
                if (_e50 < 3.5f) {
                    let _e53 = a;
                    let _e55 = b;
                    r = abs((_e53.xyz - _e55.xyz));
                } else {
                    let _e60 = a;
                    let _e63 = b;
                    let _e69 = a;
                    let _e75 = b;
                    let _e83 = a;
                    r = mix(((2f * _e60.xyz) * _e63.xyz), (vec3(1f) - ((2f * (vec3(1f) - _e69.xyz)) * (vec3(1f) - _e75.xyz))), step(vec3(0.5f), _e83.xyz));
                }
            }
        }
    }
    let _e88 = a;
    let _e90 = r;
    let _e91 = global.u_alpha;
    let _e93 = mix(_e88.xyz, _e90, vec3(_e91));
    fragColor = vec4<f32>(_e93.x, _e93.y, _e93.z, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
