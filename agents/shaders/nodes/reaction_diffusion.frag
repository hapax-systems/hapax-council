#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;
uniform float u_feed_rate;
uniform float u_kill_rate;
uniform float u_diffusion_a;
uniform float u_diffusion_b;
uniform float u_speed;
uniform float u_amount;
uniform float u_width;
uniform float u_height;

// Gray-Scott reaction-diffusion applied to camera image.
//
// Previous version stored raw A/B chemical concentrations in
// gl_FragColor (green/black wash) -- downstream nodes received
// sim data, not image data.
//
// This version runs the simulation in tex_accum (A in R, B in G)
// and uses the resulting pattern to modulate the INPUT image,
// outputting valid camera content that carries the RD pattern
// as a color/texture overlay.

void main() {
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);

    // -- Read simulation state from tex_accum --
    // Previous output had image blended with sim -- extract sim
    // from the RG channels where we encoded it.
    vec4 c = texture2D(tex_accum, v_texcoord);
    float A = c.r;
    float B = c.g;

    // -- 5-point Laplacian stencil --
    vec4 l = texture2D(tex_accum, v_texcoord - vec2(texel.x, 0.0));
    vec4 r = texture2D(tex_accum, v_texcoord + vec2(texel.x, 0.0));
    vec4 t = texture2D(tex_accum, v_texcoord - vec2(0.0, texel.y));
    vec4 b = texture2D(tex_accum, v_texcoord + vec2(0.0, texel.y));
    float lap_A = (l.r + r.r + t.r + b.r - 4.0 * A);
    float lap_B = (l.g + r.g + t.g + b.g - 4.0 * B);

    // -- Gray-Scott equations --
    float reaction = A * B * B;
    float dA = u_diffusion_a * lap_A - reaction + u_feed_rate * (1.0 - A);
    float dB = u_diffusion_b * lap_B + reaction - (u_kill_rate + u_feed_rate) * B;

    A += dA * u_speed * 0.1;
    B += dB * u_speed * 0.1;

    // -- Seed from camera input luminance --
    vec4 input_color = texture2D(tex, v_texcoord);
    float seed = dot(input_color.rgb, vec3(0.299, 0.587, 0.114));
    if (A < 0.01 && seed > 0.8) {
        B = 0.25;
    }

    A = clamp(A, 0.0, 1.0);
    B = clamp(B, 0.0, 1.0);

    // -- Apply RD pattern to camera image --
    // B concentration creates the visible pattern (spots/stripes).
    // Use it to modulate the input image rather than replacing it.
    float pattern = B * u_amount;

    // Desaturate and shift hue in pattern regions for organic look
    float luma = dot(input_color.rgb, vec3(0.299, 0.587, 0.114));
    vec3 desat = vec3(luma);
    // Pattern darkens + desaturates + slight color shift
    vec3 pattern_color = mix(input_color.rgb, desat * 0.7, pattern);
    // Add subtle edge highlight where pattern meets camera
    float edge = abs(B - 0.5) * 2.0;
    pattern_color += vec3(0.05, 0.08, 0.12) * edge * pattern;

    // -- Pack output: image with sim state encoded --
    // Blend a small amount of sim state into RG so the simulation
    // can bootstrap from tex_accum next frame.
    float sim_mix = 0.1;
    vec3 out_rgb;
    out_rgb.r = pattern_color.r * (1.0 - sim_mix) + A * sim_mix;
    out_rgb.g = pattern_color.g * (1.0 - sim_mix) + B * sim_mix;
    out_rgb.b = pattern_color.b;

    gl_FragColor = vec4(clamp(out_rgb, 0.0, 1.0), 1.0);
}
