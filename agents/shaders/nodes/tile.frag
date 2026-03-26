#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_count_x;
uniform float u_count_y;
uniform float u_mirror;
uniform float u_gap;

void main() {
    vec2 uv = v_texcoord * vec2(u_count_x, u_count_y);
    vec2 cell = floor(uv);
    vec2 f = fract(uv);
    // mirror on odd cells
    if (u_mirror > 0.5) {
        if (mod(cell.x, 2.0) > 0.5) f.x = 1.0 - f.x;
        if (mod(cell.y, 2.0) > 0.5) f.y = 1.0 - f.y;
    }
    // gap
    if (u_gap > 0.0) {
        float half_gap = u_gap * 0.5;
        if (f.x < half_gap || f.x > 1.0 - half_gap || f.y < half_gap || f.y > 1.0 - half_gap) {
            gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);
            return;
        }
        f = (f - half_gap) / (1.0 - u_gap);
    }
    gl_FragColor = texture2D(tex, f);
}
