#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_levels;
uniform float u_gamma;

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    vec3 c = pow(color.rgb, vec3(u_gamma));
    c = floor(c * u_levels + 0.5) / u_levels;
    c = pow(c, vec3(1.0 / u_gamma));
    gl_FragColor = vec4(c, color.a);
}
