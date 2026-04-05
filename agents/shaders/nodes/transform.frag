#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_pos_x;
uniform float u_pos_y;
uniform float u_scale_x;
uniform float u_scale_y;
uniform float u_rotation;
uniform float u_pivot_x;
uniform float u_pivot_y;

void main() {
    vec2 pivot = vec2(u_pivot_x, u_pivot_y);
    vec2 uv = v_texcoord - pivot;
    // rotate
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    uv = mat2(c, s, -s, c) * uv;
    // scale
    uv /= vec2(u_scale_x, u_scale_y);
    // translate
    uv -= vec2(u_pos_x, u_pos_y);
    uv += pivot;
    uv = clamp(uv, 0.0, 1.0);
    gl_FragColor = texture2D(tex, uv);
}
