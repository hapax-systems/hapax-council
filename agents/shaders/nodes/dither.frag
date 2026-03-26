#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_matrix_size;
uniform float u_color_levels;
uniform float u_monochrome;

float bayer4x4(vec2 pos) {
    int x = int(mod(pos.x, 4.0));
    int y = int(mod(pos.y, 4.0));
    int idx = x + y * 4;
    // 4x4 Bayer matrix values / 16
    if (idx == 0) return 0.0 / 16.0;
    if (idx == 1) return 8.0 / 16.0;
    if (idx == 2) return 2.0 / 16.0;
    if (idx == 3) return 10.0 / 16.0;
    if (idx == 4) return 12.0 / 16.0;
    if (idx == 5) return 4.0 / 16.0;
    if (idx == 6) return 14.0 / 16.0;
    if (idx == 7) return 6.0 / 16.0;
    if (idx == 8) return 3.0 / 16.0;
    if (idx == 9) return 11.0 / 16.0;
    if (idx == 10) return 1.0 / 16.0;
    if (idx == 11) return 9.0 / 16.0;
    if (idx == 12) return 15.0 / 16.0;
    if (idx == 13) return 7.0 / 16.0;
    if (idx == 14) return 13.0 / 16.0;
    return 5.0 / 16.0;
}

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    vec2 pixPos = gl_FragCoord.xy / u_matrix_size;
    float threshold = bayer4x4(pixPos);
    float levels = u_color_levels;
    vec3 c = color.rgb;
    if (u_monochrome > 0.5) {
        float lum = dot(c, vec3(0.299, 0.587, 0.114));
        lum = floor(lum * levels + threshold) / levels;
        gl_FragColor = vec4(vec3(lum), color.a);
    } else {
        c = floor(c * levels + threshold) / levels;
        gl_FragColor = vec4(c, color.a);
    }
}
