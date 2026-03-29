struct Params {
    u_blend: f32,
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

fn irPalette(t: f32) -> vec3<f32> {
    var t_1: f32;
    var c: vec3<f32>;

    t_1 = t;
    let _e9 = t_1;
    if (_e9 < 0.2f) {
        {
            let _e20 = t_1;
            c = mix(vec3<f32>(0f, 0f, 0.5f), vec3<f32>(0.5f, 0f, 0.5f), vec3((_e20 / 0.2f)));
        }
    } else {
        let _e25 = t_1;
        if (_e25 < 0.4f) {
            {
                let _e36 = t_1;
                c = mix(vec3<f32>(0.5f, 0f, 0.5f), vec3<f32>(1f, 0f, 0f), vec3(((_e36 - 0.2f) / 0.2f)));
            }
        } else {
            let _e43 = t_1;
            if (_e43 < 0.6f) {
                {
                    let _e54 = t_1;
                    c = mix(vec3<f32>(1f, 0f, 0f), vec3<f32>(1f, 0.5f, 0f), vec3(((_e54 - 0.4f) / 0.2f)));
                }
            } else {
                let _e61 = t_1;
                if (_e61 < 0.8f) {
                    {
                        let _e72 = t_1;
                        c = mix(vec3<f32>(1f, 0.5f, 0f), vec3<f32>(1f, 1f, 0f), vec3(((_e72 - 0.6f) / 0.2f)));
                    }
                } else {
                    {
                        let _e87 = t_1;
                        c = mix(vec3<f32>(1f, 1f, 0f), vec3<f32>(1f, 1f, 1f), vec3(((_e87 - 0.8f) / 0.2f)));
                    }
                }
            }
        }
    }
    let _e94 = c;
    return _e94;
}

fn main_1() {
    var color: vec4<f32>;
    var lum: f32;
    var mapped: vec3<f32>;

    let _e6 = v_texcoord_1;
    let _e7 = textureSample(tex, tex_sampler, _e6);
    color = _e7;
    let _e9 = color;
    lum = dot(_e9.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e17 = lum;
    let _e18 = irPalette(_e17);
    mapped = _e18;
    let _e20 = color;
    let _e22 = mapped;
    let _e23 = global.u_blend;
    let _e25 = mix(_e20.xyz, _e22, vec3(_e23));
    let _e26 = color;
    fragColor = vec4<f32>(_e25.x, _e25.y, _e25.z, _e26.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e13 = fragColor;
    return FragmentOutput(_e13);
}
