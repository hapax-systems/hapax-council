#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;
uniform float u_fade;
uniform float u_opacity;
uniform float u_blend_mode;
uniform float u_drift_x;
uniform float u_drift_y;
uniform float u_time;
uniform float u_width;
uniform float u_height;

vec3 blend_lighter(vec3 a, vec3 b) { return a + b; }
vec3 blend_screen(vec3 a, vec3 b) { return 1.0 - (1.0 - a) * (1.0 - b); }
vec3 blend_multiply(vec3 a, vec3 b) { return a * b; }
vec3 blend_difference(vec3 a, vec3 b) { return abs(a - b); }
vec3 blend_overlay(vec3 a, vec3 b) {
    return mix(2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b), step(0.5, a));
}

void main() {
    float t = u_time * 0.015;
    float dx = u_drift_x * sin(t) * 0.15 / u_width;
    float dy = u_drift_y * cos(t * 0.7) * 0.15 / u_height;
    vec4 accum = texture2D(tex_accum, v_texcoord + vec2(dx, dy));

    accum.rgb *= (1.0 - u_fade);

    vec4 current = texture2D(tex, v_texcoord);

    vec3 blended;
    if (u_blend_mode < 0.5) blended = blend_lighter(accum.rgb, current.rgb * u_opacity);
    else if (u_blend_mode < 1.5) blended = blend_screen(accum.rgb, current.rgb * u_opacity);
    else if (u_blend_mode < 2.5) blended = blend_multiply(accum.rgb, current.rgb * u_opacity);
    else if (u_blend_mode < 3.5) blended = blend_difference(accum.rgb, current.rgb * u_opacity);
    else blended = blend_overlay(accum.rgb, current.rgb * u_opacity);

    gl_FragColor = vec4(clamp(blended, 0.0, 1.0), 1.0);
}
