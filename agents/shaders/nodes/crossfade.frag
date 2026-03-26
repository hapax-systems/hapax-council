#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_b;
uniform float u_mix;

void main() {
    vec4 a = texture2D(tex, v_texcoord);
    vec4 b = texture2D(tex_b, v_texcoord);
    gl_FragColor = mix(a, b, u_mix);
}
