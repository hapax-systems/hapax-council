struct Params {
    u_radius: f32,
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
    var texel: vec2<f32>;
    var r: f32;
    var mean: array<vec3<f32>, 4>;
    var var4_: array<vec3<f32>, 4>;
    var q: i32 = 0i;
    var off: array<vec2<f32>, 4>;
    var count: f32;
    var q_1: i32 = 0i;
    var sum: vec3<f32>;
    var sumSq: vec3<f32>;
    var i: f32;
    var j: f32;
    var s: vec2<f32>;
    var c: vec3<f32>;
    var minV: vec3<f32>;
    var outColor: vec3<f32>;
    var q_2: i32 = 1i;
    var totalV: f32;
    var minTotalV: f32;
    var source: vec4<f32>;
    var source_luma: f32;
    var surface_presence: f32;
    var kuwahara_strength: f32;
    var mixed: vec3<f32>;

    source = textureSample(tex, tex_sampler, v_texcoord_1);
    source_luma = dot(source.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    surface_presence = smoothstep(0.045f, 0.18f, source_luma);
    kuwahara_strength = clamp((global.u_radius / 3.0f) * 0.42f, 0f, 0.42f) * surface_presence;
    if (kuwahara_strength <= 0.001f) {
        fragColor = source;
        return;
    }
    let _e11 = global.u_width;
    let _e14 = global.u_height;
    texel = vec2<f32>((1f / _e11), (1f / _e14));
    let _e19 = global.u_radius;
    r = max(1f, floor(_e19));
    loop {
        let _e27 = q;
        if !((_e27 < 4i)) {
            break;
        }
        {
            let _e34 = q;
            mean[_e34] = vec3(0f);
            let _e38 = q;
            var4_[_e38] = vec3(0f);
        }
        continuing {
            let _e31 = q;
            q = (_e31 + 1i);
        }
    }
    let _e45 = r;
    let _e47 = r;
    off[0i] = vec2<f32>(-(_e45), -(_e47));
    let _e53 = r;
    off[1i] = vec2<f32>(0f, -(_e53));
    let _e58 = r;
    off[2i] = vec2<f32>(-(_e58), 0f);
    off[3i] = vec2<f32>(0f, 0f);
    let _e67 = r;
    let _e70 = r;
    count = ((_e67 + 1f) * (_e70 + 1f));
    loop {
        let _e77 = q_1;
        if !((_e77 < 4i)) {
            break;
        }
        {
            sum = vec3(0f);
            sumSq = vec3(0f);
            i = 0f;
            loop {
                let _e92 = i;
                if !((_e92 <= 8f)) {
                    break;
                }
                {
                    let _e99 = i;
                    let _e100 = r;
                    if (_e99 > _e100) {
                        break;
                    }
                    j = 0f;
                    loop {
                        let _e104 = j;
                        if !((_e104 <= 8f)) {
                            break;
                        }
                        {
                            let _e111 = j;
                            let _e112 = r;
                            if (_e111 > _e112) {
                                break;
                            }
                            let _e114 = v_texcoord_1;
                            let _e115 = q_1;
                            let _e117 = off[_e115];
                            let _e118 = i;
                            let _e119 = j;
                            let _e122 = texel;
                            s = (_e114 + ((_e117 + vec2<f32>(_e118, _e119)) * _e122));
                            let _e126 = s;
                            let _e127 = textureSample(tex, tex_sampler, _e126);
                            c = _e127.xyz;
                            let _e130 = sum;
                            let _e131 = c;
                            sum = (_e130 + _e131);
                            let _e133 = sumSq;
                            let _e134 = c;
                            let _e135 = c;
                            sumSq = (_e133 + (_e134 * _e135));
                        }
                        continuing {
                            let _e108 = j;
                            j = (_e108 + 1f);
                        }
                    }
                }
                continuing {
                    let _e96 = i;
                    i = (_e96 + 1f);
                }
            }
            let _e138 = q_1;
            let _e140 = sum;
            let _e141 = count;
            mean[_e138] = (_e140 / vec3(_e141));
            let _e144 = q_1;
            let _e146 = sumSq;
            let _e147 = count;
            let _e150 = q_1;
            let _e152 = mean[_e150];
            let _e153 = q_1;
            let _e155 = mean[_e153];
            var4_[_e144] = ((_e146 / vec3(_e147)) - (_e152 * _e155));
        }
        continuing {
            let _e81 = q_1;
            q_1 = (_e81 + 1i);
        }
    }
    let _e160 = var4_[0];
    minV = _e160;
    let _e164 = mean[0];
    outColor = _e164;
    loop {
        let _e168 = q_2;
        if !((_e168 < 4i)) {
            break;
        }
        {
            let _e175 = q_2;
            let _e177 = var4_[_e175];
            let _e179 = q_2;
            let _e181 = var4_[_e179];
            let _e184 = q_2;
            let _e186 = var4_[_e184];
            totalV = ((_e177.x + _e181.y) + _e186.z);
            let _e190 = minV;
            let _e192 = minV;
            let _e195 = minV;
            minTotalV = ((_e190.x + _e192.y) + _e195.z);
            let _e199 = totalV;
            let _e200 = minTotalV;
            if (_e199 < _e200) {
                {
                    let _e202 = q_2;
                    let _e204 = var4_[_e202];
                    minV = _e204;
                    let _e205 = q_2;
                    let _e207 = mean[_e205];
                    outColor = _e207;
                }
            }
        }
        continuing {
            let _e172 = q_2;
            q_2 = (_e172 + 1i);
        }
    }
    let _e208 = outColor;
    mixed = mix(source.xyz, _e208, vec3(kuwahara_strength));
    fragColor = vec4<f32>(mixed.x, mixed.y, mixed.z, source.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e17 = fragColor;
    return FragmentOutput(_e17);
}
