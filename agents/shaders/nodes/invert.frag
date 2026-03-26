#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_strength;

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    vec3 inverted = vec3(1.0) - color.rgb;
    gl_FragColor = vec4(mix(color.rgb, inverted, u_strength), color.a);
}
