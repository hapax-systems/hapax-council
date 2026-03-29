struct Params {
    u_emit_rate: f32,
    u_lifetime: f32,
    u_size: f32,
    u_color_r: f32,
    u_color_g: f32,
    u_color_b: f32,
    u_gravity_y: f32,
    u_time: f32,
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

fn hash(n: f32) -> f32 {
    var n_1: f32;

    n_1 = n;
    let _e26 = n_1;
    return fract((sin(_e26) * 43758.547f));
}

fn main_1() {
    var base: vec4<f32>;
    var pixel: vec2<f32>;
    var particle_count: f32;
    var glow: f32 = 0f;
    var i: f32 = 0f;
    var age: f32;
    var spawn_x: f32;
    var spawn_y: f32;
    var vel_x: f32;
    var vel_y: f32;
    var px: f32;
    var py: f32;
    var dist: f32;
    var fade: f32;
    var particle_color: vec3<f32>;

    let _e24 = v_texcoord_1;
    let _e25 = textureSample(tex, tex_sampler, _e24);
    base = _e25;
    let _e27 = v_texcoord_1;
    let _e28 = global.u_width;
    let _e29 = global.u_height;
    pixel = (_e27 * vec2<f32>(_e28, _e29));
    let _e33 = global.u_emit_rate;
    particle_count = min(_e33, 2000f);
    loop {
        let _e41 = i;
        if !((_e41 < 200f)) {
            break;
        }
        {
            let _e48 = i;
            let _e49 = particle_count;
            if (_e48 >= _e49) {
                break;
            }
            let _e51 = global.u_time;
            let _e52 = global.u_lifetime;
            let _e54 = i;
            let _e57 = hash((_e54 * 7.31f));
            age = fract(((_e51 / _e52) + _e57));
            let _e61 = i;
            let _e64 = hash((_e61 * 13.7f));
            let _e65 = global.u_width;
            spawn_x = (_e64 * _e65);
            let _e68 = i;
            let _e71 = hash((_e68 * 23.1f));
            let _e72 = global.u_height;
            spawn_y = (_e71 * _e72);
            let _e75 = i;
            let _e78 = hash((_e75 * 37.3f));
            vel_x = ((_e78 - 0.5f) * 100f);
            let _e84 = i;
            let _e87 = hash((_e84 * 41.7f));
            vel_y = ((_e87 - 0.5f) * 100f);
            let _e93 = spawn_x;
            let _e94 = vel_x;
            let _e95 = age;
            px = (_e93 + (_e94 * _e95));
            let _e99 = spawn_y;
            let _e100 = vel_y;
            let _e101 = age;
            let _e105 = global.u_gravity_y;
            let _e107 = age;
            let _e109 = age;
            py = ((_e99 + (_e100 * _e101)) + (((0.5f * _e105) * _e107) * _e109));
            let _e113 = pixel;
            let _e114 = px;
            let _e115 = py;
            dist = length((_e113 - vec2<f32>(_e114, _e115)));
            let _e121 = age;
            fade = (1f - _e121);
            let _e124 = glow;
            let _e125 = fade;
            let _e126 = global.u_size;
            let _e128 = dist;
            glow = (_e124 + (_e125 * smoothstep(_e126, 0f, _e128)));
        }
        continuing {
            let _e45 = i;
            i = (_e45 + 1f);
        }
    }
    let _e132 = global.u_color_r;
    let _e133 = global.u_color_g;
    let _e134 = global.u_color_b;
    let _e136 = glow;
    particle_color = (vec3<f32>(_e132, _e133, _e134) * min(_e136, 3f));
    let _e141 = base;
    let _e143 = particle_color;
    let _e144 = (_e141.xyz + _e143);
    fragColor = vec4<f32>(_e144.x, _e144.y, _e144.z, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e31 = fragColor;
    return FragmentOutput(_e31);
}
