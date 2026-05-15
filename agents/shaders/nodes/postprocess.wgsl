struct Params {
    u_vignette_strength: f32,
    u_sediment_strength: f32,
    u_master_opacity: f32,
    u_anonymize: f32,
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

fn hash(p: vec2<f32>) -> f32 {
    var p3 = fract(vec3<f32>(p.x, p.y, p.x) * 0.1031);
    p3 = p3 + dot(p3, p3.yzx + vec3<f32>(19.19));
    return fract((p3.x + p3.y) * p3.z);
}

fn main_1() {
    var c: vec4<f32>;

    let _e8 = v_texcoord_1;
    let _e9 = textureSample(tex, tex_sampler, _e8);
    c = _e9;

    let mediation = clamp(global.u_anonymize, 0.0, 0.65);
    if mediation > 0.001 {
        let luminance = dot(c.xyz, vec3<f32>(0.299, 0.587, 0.114));
        let poster_levels = mix(14.0, 7.0, mediation);
        let poster = floor(c.xyz * poster_levels + vec3<f32>(0.5)) / poster_levels;
        let n = hash(v_texcoord_1 * vec2<f32>(270.0, 180.0) + c.rg * 3.0 + vec2<f32>(uniforms.time * 0.06, 0.0));
        let scan = sin((v_texcoord_1.y * 720.0) * 1.35 + uniforms.time * 1.7) * 0.5 + 0.5;
        let veil = vec3<f32>(
            n - 0.5,
            hash(v_texcoord_1 * 330.0 + vec2<f32>(11.7, uniforms.time * 0.04)) - 0.5,
            scan - 0.5,
        );
        let mediated = poster + veil * (0.10 + 0.12 * mediation) + vec3<f32>(luminance * 0.04 * mediation);
        c = vec4<f32>(mix(c.xyz, mediated, vec3<f32>(0.36 + 0.34 * mediation)), c.w);
    }

    // Elliptical vignette: UV mapped to centered -1..1 on both axes.
    // No aspect correction — uniform edge darkening at all screen edges.
    let uv = (v_texcoord_1 * 2.0) - vec2(1.0);
    let d = length(uv);
    let vig = smoothstep(1.0, 2.0, d) * global.u_vignette_strength;
    c = vec4<f32>(c.xyz * (1.0 - vig), c.w);

    // Sediment: bottom-edge darkening
    let sed = smoothstep(0.95, 1.0, v_texcoord_1.y) * global.u_sediment_strength;
    c = vec4<f32>(c.xyz * (1.0 - sed), c.w);

    // Master opacity gate — black when nothing is recruited
    c = vec4<f32>(c.xyz * global.u_master_opacity, c.w);

    fragColor = c;
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e15 = fragColor;
    return FragmentOutput(_e15);
}
