struct Params {
    u_block_size: f32,
    u_intensity: f32,
    u_rgb_split: f32,
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
var<private> gl_FragCoord_1: vec4<f32>;

fn blockHash(blockID: vec2<f32>, seed: f32) -> f32 {
    var blockID_1: vec2<f32>;
    var seed_1: f32;

    blockID_1 = blockID;
    seed_1 = seed;
    let _e20 = blockID_1;
    let _e21 = seed_1;
    return fract((sin(dot((_e20 + vec2(_e21)), vec2<f32>(12.9898f, 78.233f))) * 43758.547f));
}

fn main_1() {
    var uv: vec2<f32>;
    var pixel: vec2<f32>;
    var blockID_2: vec2<f32>;
    var timeSlot: f32;
    var h: f32;
    var corruptThreshold: f32;
    var effectType: f32;
    var shiftX: f32;
    var shiftY: f32;
    var displaced: vec2<f32>;
    var split: f32;
    var r: f32;
    var g: f32;
    var b: f32;
    var color: vec4<f32>;
    var bright: f32;
    var color_1: vec4<f32>;
    var swapSeed: f32;
    var v: f32;
    var pixel_1: vec2<f32>;
    var pattern: f32;
    var patternR: f32;

    let _e16 = v_texcoord_1;
    uv = _e16;
    let _e18 = global.u_intensity;
    if (_e18 < 0.01f) {
        {
            let _e21 = uv;
            let _e22 = textureSample(tex, tex_sampler, _e21);
            fragColor = _e22;
            return;
        }
    }
    let _e24 = gl_FragCoord_1;
    pixel = _e24.xy;
    let _e27 = pixel;
    let _e28 = global.u_block_size;
    blockID_2 = floor((_e27 / vec2(_e28)));

    timeSlot = floor((uniforms.time * 5f));
    let _e38 = blockID_2;
    let _e39 = timeSlot;
    let _e40 = blockHash(_e38, _e39);
    h = _e40;
    let _e42 = global.u_intensity;
    corruptThreshold = (_e42 * 0.4f);
    let _e46 = h;
    let _e47 = corruptThreshold;
    if (_e46 < _e47) {
        {
            let _e49 = blockID_2;
            let _e50 = timeSlot;
            let _e53 = blockHash(_e49, (_e50 + 10f));
            effectType = _e53;
            let _e55 = effectType;
            if (_e55 < 0.4f) {
                {
                    let _e58 = blockID_2;
                    let _e59 = timeSlot;
                    let _e62 = blockHash(_e58, (_e59 + 1f));

                    shiftX = (((_e62 - 0.5f) * 60f) / uniforms.resolution.x);
                    let _e70 = blockID_2;
                    let _e71 = timeSlot;
                    let _e74 = blockHash(_e70, (_e71 + 2f));

                    shiftY = (((_e74 - 0.5f) * 6f) / uniforms.resolution.y);
                    let _e82 = uv;
                    let _e83 = shiftX;
                    let _e84 = shiftY;
                    let _e86 = global.u_intensity;
                    displaced = (_e82 + (vec2<f32>(_e83, _e84) * _e86));
                    let _e90 = global.u_rgb_split;
                    let _e91 = blockID_2;
                    let _e92 = timeSlot;
                    let _e95 = blockHash(_e91, (_e92 + 3f));

                    split = (((_e90 * _e95) * 8f) / uniforms.resolution.x);
                    let _e102 = displaced;
                    let _e103 = split;
                    let _e107 = textureSample(tex, tex_sampler, (_e102 + vec2<f32>(_e103, 0f)));
                    r = _e107.x;
                    let _e110 = displaced;
                    let _e111 = textureSample(tex, tex_sampler, _e110);
                    g = _e111.y;
                    let _e114 = displaced;
                    let _e115 = split;
                    let _e119 = textureSample(tex, tex_sampler, (_e114 - vec2<f32>(_e115, 0f)));
                    b = _e119.z;
                    let _e122 = r;
                    let _e123 = g;
                    let _e124 = b;
                    fragColor = vec4<f32>(_e122, _e123, _e124, 1f);
                    return;
                }
            } else {
                let _e127 = effectType;
                if (_e127 < 0.55f) {
                    {
                        let _e130 = uv;
                        let _e131 = textureSample(tex, tex_sampler, _e130);
                        color = _e131;
                        let _e133 = blockID_2;
                        let _e134 = timeSlot;
                        let _e137 = blockHash(_e133, (_e134 + 4f));
                        bright = (_e137 * 2f);
                        let _e141 = color;
                        let _e143 = color;
                        let _e145 = bright;
                        let _e146 = (_e143.xyz * _e145);
                        color.x = _e146.x;
                        color.y = _e146.y;
                        color.z = _e146.z;
                        let _e153 = color;
                        let _e155 = color;
                        let _e162 = (floor((_e155.xyz * 4f)) / vec3(4f));
                        color.x = _e162.x;
                        color.y = _e162.y;
                        color.z = _e162.z;
                        let _e169 = color;
                        fragColor = clamp(_e169, vec4(0f), vec4(1f));
                        return;
                    }
                } else {
                    let _e175 = effectType;
                    if (_e175 < 0.85f) {
                        {
                            let _e178 = uv;
                            let _e179 = textureSample(tex, tex_sampler, _e178);
                            color_1 = _e179;
                            let _e181 = blockID_2;
                            let _e182 = timeSlot;
                            let _e185 = blockHash(_e181, (_e182 + 5f));
                            swapSeed = _e185;
                            let _e187 = swapSeed;
                            if (_e187 < 0.33f) {
                                let _e190 = color_1;
                                let _e192 = color_1;
                                let _e194 = color_1;
                                fragColor = vec4<f32>(_e190.z, _e192.x, _e194.y, 1f);
                                return;
                            } else {
                                let _e198 = swapSeed;
                                if (_e198 < 0.66f) {
                                    let _e201 = color_1;
                                    let _e203 = color_1;
                                    let _e205 = color_1;
                                    fragColor = vec4<f32>(_e201.y, _e203.z, _e205.x, 1f);
                                    return;
                                } else {
                                    let _e209 = color_1;
                                    let _e211 = color_1;
                                    let _e213 = color_1;
                                    fragColor = vec4<f32>(_e209.x, _e211.z, _e213.y, 1f);
                                    return;
                                }
                            }
                        }
                    } else {
                        let _e217 = effectType;
                        if (_e217 < 0.9f) {
                            {
                                let _e220 = blockID_2;
                                let _e221 = timeSlot;
                                let _e224 = blockHash(_e220, (_e221 + 6f));
                                v = _e224;
                                let _e226 = v;
                                let _e229 = vec3((_e226 * 0.3f));
                                fragColor = vec4<f32>(_e229.x, _e229.y, _e229.z, 1f);
                                return;
                            }
                        } else {
                            {
                                let _e235 = gl_FragCoord_1;
                                pixel_1 = _e235.xy;
                                let _e238 = pixel_1;
                                let _e240 = pixel_1;
                                let _e244 = (_e238.x + (_e240.y * 3f));
                                pattern = ((_e244 - (floor((_e244 / 8f)) * 8f)) / 8f);
                                let _e253 = pixel_1;
                                let _e257 = pixel_1;
                                let _e259 = ((_e253.x * 2f) + _e257.y);
                                patternR = ((_e259 - (floor((_e259 / 6f)) * 6f)) / 6f);
                                let _e268 = pattern;
                                let _e269 = patternR;
                                let _e272 = pattern;
                                fragColor = vec4<f32>(_e268, (_e269 * 0.7f), (_e272 * 0.5f), 1f);
                                return;
                            }
                        }
                    }
                }
            }
        }
    } else {
        {
            let _e277 = uv;
            let _e278 = textureSample(tex, tex_sampler, _e277);
            fragColor = _e278;
            return;
        }
    }
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>, @builtin(position) gl_FragCoord: vec4<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    gl_FragCoord_1 = gl_FragCoord;
    main_1();
    let _e25 = fragColor;
    return FragmentOutput(_e25);
}
