#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform float u_frequency_x;
uniform float u_frequency_y;
uniform float u_octaves;
uniform float u_amplitude;
uniform float u_speed;
uniform float u_time;
float hash(vec2 p) {
    p = fract(p * vec2(0.1031, 0.1030));
    p += dot(p, p.yx + 33.33);
    return fract((p.x + p.y) * p.x);
}
float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
float fbm(vec2 p, float oct) {
    float v = 0.0;
    float a = 0.5;
    vec2 shift = vec2(100.0);
    for (int i = 0; i < 8; i++) {
        if (float(i) >= oct) break;
        v += a * noise(p);
        p = p * 2.0 + shift;
        a *= 0.5;
    }
    return v;
}
void main() {
    vec2 uv = v_texcoord * vec2(u_frequency_x, u_frequency_y);
    uv += u_time * u_speed * 0.1;
    float n = fbm(uv, u_octaves) * u_amplitude;
    gl_FragColor = vec4(vec3(n), 1.0);
}
