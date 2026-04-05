#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_rate;
uniform float u_amplitude;
uniform float u_time;

#define PI 3.14159265359

void main() {
    float scale = 1.0 + sin(u_time * u_rate * 2.0 * PI) * u_amplitude;
    vec2 center = vec2(0.5, 0.5);
    vec2 uv = (v_texcoord - center) / scale + center;
    // Clamp to edge instead of outputting black — prevents black borders
    // from poisoning downstream trail/feedback presets.
    uv = clamp(uv, 0.0, 1.0);
    gl_FragColor = texture2D(tex, uv);
}
