#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_strength;
uniform float u_radius;
uniform float u_softness;
void main() {
    vec4 c = texture2D(tex, v_texcoord);
    float d = length(v_texcoord - 0.5) * 2.0;
    c.rgb *= 1.0 - smoothstep(u_radius, u_radius + u_softness, d) * u_strength;
    gl_FragColor = c;
}
