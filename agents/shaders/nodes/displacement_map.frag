#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_b;
uniform float u_strength_x;
uniform float u_strength_y;

void main() {
    vec2 uv = v_texcoord;
    vec4 disp = texture2D(tex_b, uv);
    vec2 offset = (disp.rg - 0.5) * 2.0 * vec2(u_strength_x, u_strength_y) * 0.1;
    gl_FragColor = texture2D(tex, uv + offset);
}
