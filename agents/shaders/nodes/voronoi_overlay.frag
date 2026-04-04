#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_cell_count;
uniform float u_edge_width;
uniform float u_animation_speed;
uniform float u_jitter;
uniform float u_time;

vec2 hash2(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    p3 += dot(p3, p3.yzx + 19.19);
    return fract((p3.xx + p3.yz) * p3.zy);
}

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    vec2 uv = v_texcoord * u_cell_count;
    vec2 cell = floor(uv);
    vec2 frac_uv = fract(uv);
    float minDist = 10.0;
    float secondDist = 10.0;
    for (int y = -1; y <= 1; y++) {
        for (int x = -1; x <= 1; x++) {
            vec2 neighbor = vec2(float(x), float(y));
            vec2 point = hash2(cell + neighbor);
            point = 0.5 + u_jitter * 0.5 * sin(u_time * u_animation_speed + 6.2831 * point);
            float d = length(neighbor + point - frac_uv);
            if (d < minDist) {
                secondDist = minDist;
                minDist = d;
            } else if (d < secondDist) {
                secondDist = d;
            }
        }
    }
    float edge = smoothstep(0.0, u_edge_width, secondDist - minDist);
    gl_FragColor = vec4(color.rgb * edge, color.a);
}
