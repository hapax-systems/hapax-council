#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_segments;
uniform float u_center_x;
uniform float u_center_y;
uniform float u_rotation;

#define PI 3.14159265359

void main() {
    vec2 center = vec2(u_center_x, u_center_y);
    vec2 uv = v_texcoord - center;
    float angle = atan(uv.y, uv.x) + u_rotation;
    float r = length(uv);
    float segAngle = 2.0 * PI / u_segments;
    angle = mod(angle, segAngle);
    if (angle > segAngle * 0.5) {
        angle = segAngle - angle;
    }
    vec2 newUV = center + r * vec2(cos(angle), sin(angle));
    newUV = clamp(newUV, 0.0, 1.0);
    gl_FragColor = texture2D(tex, newUV);
}
