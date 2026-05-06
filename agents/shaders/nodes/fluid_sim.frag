#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;
uniform float u_viscosity;
uniform float u_vorticity;
uniform float u_dissipation;
uniform float u_speed;
uniform float u_amount;
uniform float u_time;
uniform float u_width;
uniform float u_height;

// Procedural water-ripple displacement applied to the camera image.
//
// Previous version stored raw velocity/density simulation state in
// gl_FragColor — blue/white wash when placed inline in the shader
// chain because downstream nodes received sim data, not image data.
//
// This version runs a lightweight displacement field via tex_accum
// (velocity in RG, encoded 0-1) and outputs the displaced INPUT
// image so the shader chain always carries valid camera content.

void main() {
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);

    // ── Read previous velocity field from tex_accum (RG channels) ──
    vec4 prev = texture2D(tex_accum, v_texcoord);
    vec2 vel = prev.rg * 2.0 - 1.0;

    // ── Advect ──
    vec2 advected_uv = v_texcoord - vel * texel * u_speed;
    vec4 advected = texture2D(tex_accum, advected_uv);

    // ── Diffusion: average with neighbors ──
    vec4 l = texture2D(tex_accum, v_texcoord - vec2(texel.x, 0.0));
    vec4 r = texture2D(tex_accum, v_texcoord + vec2(texel.x, 0.0));
    vec4 t = texture2D(tex_accum, v_texcoord - vec2(0.0, texel.y));
    vec4 b = texture2D(tex_accum, v_texcoord + vec2(0.0, texel.y));
    vec4 diffused = mix(advected, (l + r + t + b) * 0.25, u_viscosity * 10.0);

    // ── Vorticity confinement ──
    float curl = (r.g - l.g) - (t.r - b.r);
    vec2 vort = vec2(
        abs(texture2D(tex_accum, v_texcoord + vec2(0.0, texel.y)).r) -
        abs(texture2D(tex_accum, v_texcoord - vec2(0.0, texel.y)).r),
        abs(texture2D(tex_accum, v_texcoord + vec2(texel.x, 0.0)).g) -
        abs(texture2D(tex_accum, v_texcoord - vec2(texel.x, 0.0)).g)
    );
    vort = normalize(vort + vec2(0.0001)) * curl * u_vorticity * texel.x;

    // ── Inject from input luminance gradient ──
    float lum_c = dot(texture2D(tex, v_texcoord).rgb, vec3(0.299, 0.587, 0.114));
    float lum_l = dot(texture2D(tex, v_texcoord - vec2(texel.x * 3.0, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lum_r = dot(texture2D(tex, v_texcoord + vec2(texel.x * 3.0, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lum_t = dot(texture2D(tex, v_texcoord - vec2(0.0, texel.y * 3.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lum_b = dot(texture2D(tex, v_texcoord + vec2(0.0, texel.y * 3.0)).rgb, vec3(0.299, 0.587, 0.114));
    vec2 grad = vec2(lum_r - lum_l, lum_b - lum_t) * 0.15;

    // ── Update velocity ──
    vec2 new_vel = (diffused.rg * 2.0 - 1.0 + vort + grad) * u_dissipation;

    // ── Apply velocity as displacement to the INPUT image ──
    float amt = u_amount;
    vec2 displacement = new_vel * amt;
    vec2 displaced_uv = v_texcoord + displacement;
    displaced_uv = clamp(displaced_uv, vec2(0.0), vec2(1.0));
    vec4 displaced_color = texture2D(tex, displaced_uv);

    // ── Pack output: displaced image in RGB, velocity in RG of a ──
    // ── separate encoding. We use a blend: the output is mostly   ──
    // ── the displaced image, but we encode velocity into the alpha ──
    // ── channel region by mixing a tiny amount of sim state.       ──
    //
    // Since glfeedback stores our output as next frame's tex_accum,
    // we need velocity info to survive. Strategy: store velocity
    // encoded in RG but make the output visually correct by weighting
    // the image heavily. The sim reads prev.rg so we need vel there.
    //
    // Compromise: output the displaced image but blend a small amount
    // of velocity encoding so the sim can bootstrap from it next frame.
    vec2 vel_encoded = new_vel * 0.5 + 0.5;
    // Mix: 90% displaced image, 10% velocity encoding in RG
    // This keeps the image visually dominant while preserving enough
    // velocity signal for the sim to advect coherently.
    float sim_mix = 0.08;
    vec3 out_rgb = displaced_color.rgb * (1.0 - sim_mix) +
                   vec3(vel_encoded, displaced_color.b) * sim_mix;

    gl_FragColor = vec4(clamp(out_rgb, 0.0, 1.0), 1.0);
}
