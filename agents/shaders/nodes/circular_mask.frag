#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_radius;
uniform float u_softness;

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    vec2 center = vec2(0.5, 0.5);
    float dist = distance(v_texcoord, center);
    float mask = 1.0 - smoothstep(u_radius - u_softness, u_radius, dist);
    gl_FragColor = vec4(color.rgb, color.a * mask);
}
