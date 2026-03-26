#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_speed;
uniform float u_twist;
uniform float u_radius;
uniform float u_distortion;
uniform float u_time;

#define PI 3.14159265359

void main() {
    vec2 uv = v_texcoord - 0.5;
    float r = length(uv);
    float angle = atan(uv.y, uv.x);
    // tunnel mapping: cylindrical projection
    float tunnel_r = u_radius / (r + 0.001);
    float tunnel_a = angle / PI;
    // animate
    tunnel_r += u_time * u_speed;
    tunnel_a += u_twist * tunnel_r * 0.1;
    // distortion
    tunnel_a += sin(tunnel_r * u_distortion) * 0.1;
    // map to texture coords
    vec2 tunnelUV = vec2(tunnel_a, fract(tunnel_r));
    tunnelUV = fract(tunnelUV);
    vec4 color = texture2D(tex, tunnelUV);
    // fade at edges
    float fade = smoothstep(0.0, 0.1, r);
    gl_FragColor = vec4(color.rgb * fade, color.a);
}
