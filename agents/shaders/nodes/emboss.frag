#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_angle;
uniform float u_strength;
uniform float u_blend;
uniform float u_width;
uniform float u_height;

void main() {
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);
    float c = cos(u_angle);
    float s = sin(u_angle);
    vec2 dir = vec2(c, s) * texel;
    vec4 color = texture2D(tex, v_texcoord);
    vec4 s1 = texture2D(tex, v_texcoord + dir);
    vec4 s2 = texture2D(tex, v_texcoord - dir);
    vec3 embossed = (s1.rgb - s2.rgb) * u_strength + 0.5;
    gl_FragColor = vec4(mix(color.rgb, embossed, u_blend), color.a);
}
