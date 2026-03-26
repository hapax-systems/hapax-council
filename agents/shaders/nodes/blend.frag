#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_b;
uniform float u_alpha;
uniform float u_mode;

vec3 blend_screen(vec3 a, vec3 b) { return 1.0 - (1.0 - a) * (1.0 - b); }
vec3 blend_lighter(vec3 a, vec3 b) { return a + b; }
vec3 blend_multiply(vec3 a, vec3 b) { return a * b; }
vec3 blend_difference(vec3 a, vec3 b) { return abs(a - b); }
vec3 blend_overlay(vec3 a, vec3 b) {
    return mix(2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b), step(0.5, a));
}
vec3 blend_soft_light(vec3 a, vec3 b) {
    return mix(
        2.0 * a * b + a * a * (1.0 - 2.0 * b),
        sqrt(a) * (2.0 * b - 1.0) + 2.0 * a * (1.0 - b),
        step(0.5, b)
    );
}
vec3 blend_hard_light(vec3 a, vec3 b) {
    return mix(2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b), step(0.5, b));
}

void main() {
    vec4 a = texture2D(tex, v_texcoord);
    vec4 b = texture2D(tex_b, v_texcoord);

    vec3 blended;
    if (u_mode < 0.5) blended = blend_screen(a.rgb, b.rgb);
    else if (u_mode < 1.5) blended = blend_lighter(a.rgb, b.rgb);
    else if (u_mode < 2.5) blended = blend_multiply(a.rgb, b.rgb);
    else if (u_mode < 3.5) blended = blend_difference(a.rgb, b.rgb);
    else if (u_mode < 4.5) blended = blend_overlay(a.rgb, b.rgb);
    else if (u_mode < 5.5) blended = blend_soft_light(a.rgb, b.rgb);
    else blended = blend_hard_light(a.rgb, b.rgb);

    gl_FragColor = vec4(mix(a.rgb, blended, u_alpha), 1.0);
}
