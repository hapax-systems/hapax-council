struct Params {
    u_time: f32,
    u_slice_count: f32,
    u_slice_amplitude: f32,
    u_pan_x: f32,
    u_pan_y: f32,
    u_rotation: f32,
    u_zoom: f32,
    u_zoom_breath: f32,
    u_width: f32,
    u_height: f32,
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
    var t: f32;
    var panX: f32;
    var panY: f32;
    var rot: f32;
    var zoom: f32;
    var c: f32;
    var s: f32;
    var sliceIdx: f32;
    var slicePhase: f32;
    var sliceShift: f32;

    let _e24 = v_texcoord_1;
    uv = _e24;
    let _e26 = global.u_time;
    t = _e26;
    let _e28 = t;
    let _e30 = global.u_pan_x;
    let _e32 = global.u_width;
    panX = ((sin(_e28) * _e30) / _e32);
    let _e35 = t;
    let _e39 = global.u_pan_y;
    let _e41 = global.u_height;
    panY = ((sin((_e35 * 0.7f)) * _e39) / _e41);
    let _e44 = t;
    let _e48 = global.u_rotation;
    rot = (sin((_e44 * 0.5f)) * _e48);
    let _e51 = global.u_zoom;
    let _e52 = t;
    let _e56 = global.u_zoom_breath;
    zoom = (_e51 + (sin((_e52 * 0.2f)) * _e56));
    let _e60 = uv;
    uv = (_e60 - vec2(0.5f));
    let _e64 = rot;
    c = cos(_e64);
    let _e67 = rot;
    s = sin(_e67);
    let _e70 = c;
    let _e71 = s;
    let _e73 = s;
    let _e74 = c;
    let _e78 = uv;
    uv = (mat2x2<f32>(vec2<f32>(_e70, -(_e71)), vec2<f32>(_e73, _e74)) * _e78);
    let _e80 = uv;
    let _e81 = zoom;
    uv = (_e80 / vec2(_e81));
    let _e84 = uv;
    uv = (_e84 + vec2(0.5f));
    let _e88 = uv;
    let _e89 = panX;
    let _e90 = panY;
    uv = (_e88 + vec2<f32>(_e89, _e90));
    let _e93 = global.u_slice_count;
    if (_e93 > 0f) {
        {
            let _e96 = v_texcoord_1;
            let _e98 = global.u_slice_count;
            sliceIdx = floor((_e96.y * _e98));
            let _e102 = t;
            let _e103 = sliceIdx;
            slicePhase = (_e102 + (_e103 * 0.15f));
            let _e108 = slicePhase;
            let _e110 = global.u_slice_amplitude;
            let _e112 = global.u_width;
            sliceShift = ((sin(_e108) * _e110) / _e112);
            let _e115 = sliceShift;
            let _e116 = slicePhase;
            let _e120 = global.u_slice_amplitude;
            let _e124 = global.u_width;
            sliceShift = (_e115 + ((sin((_e116 * 2.3f)) * (_e120 * 0.5f)) / _e124));
            let _e128 = uv;
            let _e130 = sliceShift;
            uv.x = (_e128.x + _e130);
        }
    }
    let _e132 = uv;
    let _e133 = textureSample(tex, tex_sampler, _e132);
    fragColor = _e133;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e31 = fragColor;
    return FragmentOutput(_e31);
}
