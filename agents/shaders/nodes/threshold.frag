#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_level;
uniform float u_softness;

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    float edge = u_softness * 0.5;
    float t = smoothstep(u_level - edge, u_level + edge, lum);
    gl_FragColor = vec4(vec3(t), color.a);
}
