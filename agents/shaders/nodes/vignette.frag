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
    vec4 color = texture2D(tex, v_texcoord);
    vec2 center = v_texcoord - 0.5;
    float dist = length(center) * 2.0;
    float vig = smoothstep(u_radius, u_radius + u_softness, dist);
    color.rgb *= 1.0 - vig * u_strength;
    gl_FragColor = color;
}
