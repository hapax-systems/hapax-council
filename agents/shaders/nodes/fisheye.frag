#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_strength;
uniform float u_center_x;
uniform float u_center_y;
uniform float u_zoom;

void main() {
    vec2 center = vec2(u_center_x, u_center_y);
    vec2 uv = v_texcoord - center;
    float r = length(uv);
    float theta = atan(uv.y, uv.x);
    float rd = r * (1.0 + u_strength * r * r);
    vec2 distorted = center + rd * vec2(cos(theta), sin(theta)) / u_zoom;
    distorted = clamp(distorted, 0.0, 1.0);
    gl_FragColor = texture2D(tex, distorted);
}
