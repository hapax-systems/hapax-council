struct Params {
    u_threshold: f32,
    u_radius: f32,
    u_alpha: f32,
    u_width: f32,
    u_height: f32,
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

fn main_1() {
    var c: vec4<f32>;
    var tx: vec2<f32>;
    var g: vec3<f32> = vec3(0f);
    var t: f32 = 0f;
    var x: f32 = -2f;
    var y: f32;
    var s: vec4<f32>;
    var l: f32;
    var b: f32;
    var w: f32;

    let _e14 = v_texcoord_1;
    let _e15 = textureSample(tex, tex_sampler, _e14);
    c = _e15;
    let _e18 = global.u_width;
    let _e21 = global.u_height;
    let _e24 = global.u_radius;
    tx = ((vec2<f32>((1f / _e18), (1f / _e21)) * _e24) * 0.25f);
    loop {
        let _e37 = x;
        if !((_e37 <= 2f)) {
            break;
        }
        y = -2f;
        loop {
            let _e47 = y;
            if !((_e47 <= 2f)) {
                break;
            }
            {
                let _e54 = v_texcoord_1;
                let _e55 = x;
                let _e56 = y;
                let _e58 = tx;
                let _e61 = textureSample(tex, tex_sampler, (_e54 + (vec2<f32>(_e55, _e56) * _e58)));
                s = _e61;
                let _e63 = s;
                l = dot(_e63.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
                let _e71 = global.u_threshold;
                let _e74 = global.u_threshold;
                let _e77 = l;
                b = smoothstep((_e71 - 0.1f), (_e74 + 0.1f), _e77);
                let _e80 = x;
                let _e81 = x;
                let _e83 = y;
                let _e84 = y;
                w = exp((-(((_e80 * _e81) + (_e83 * _e84))) / 4f));
                let _e92 = g;
                let _e93 = s;
                let _e95 = b;
                let _e97 = w;
                g = (_e92 + ((_e93.xyz * _e95) * _e97));
                let _e100 = t;
                let _e101 = w;
                t = (_e100 + _e101);
            }
            continuing {
                let _e51 = y;
                y = (_e51 + 1f);
            }
        }
        continuing {
            let _e41 = x;
            x = (_e41 + 1f);
        }
    }
    let _e103 = c;
    let _e105 = c;
    let _e107 = g;
    let _e108 = t;
    let _e111 = global.u_alpha;
    let _e113 = (_e105.xyz + ((_e107 / vec3(_e108)) * _e111));
    c.x = _e113.x;
    c.y = _e113.y;
    c.z = _e113.z;
    let _e120 = c;
    let _e126 = clamp(_e120.xyz, vec3(0f), vec3(1f));
    let _e127 = c;
    fragColor = vec4<f32>(_e126.x, _e126.y, _e126.z, _e127.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
