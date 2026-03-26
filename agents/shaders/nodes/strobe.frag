#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_active;
uniform float u_color_r;
uniform float u_color_g;
uniform float u_color_b;
uniform float u_color_a;

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    if (u_active > 0.5) {
        vec4 flash = vec4(u_color_r, u_color_g, u_color_b, u_color_a);
        gl_FragColor = mix(color, flash, flash.a);
    } else {
        gl_FragColor = color;
    }
}
