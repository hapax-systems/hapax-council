#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_offset_x;
uniform float u_offset_y;
uniform float u_intensity;

void main() {
    vec2 uv = v_texcoord;
    vec2 offset = vec2(u_offset_x, u_offset_y) * u_intensity * 0.01;
    float r = texture2D(tex, uv + offset).r;
    float g = texture2D(tex, uv).g;
    float b = texture2D(tex, uv - offset).b;
    float a = texture2D(tex, uv).a;
    gl_FragColor = vec4(r, g, b, a);
}
