#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform float u_color_r;
uniform float u_color_g;
uniform float u_color_b;
uniform float u_color_a;

void main() {
    gl_FragColor = vec4(u_color_r, u_color_g, u_color_b, u_color_a);
}
