#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform float u_shape;
uniform float u_thickness;
uniform float u_color_r;
uniform float u_color_g;
uniform float u_color_b;
uniform float u_color_a;
uniform float u_scale;
uniform float u_time;
float hash(vec2 p) {
    p = fract(p * vec2(0.1031, 0.1030));
    p += dot(p, p.yx + 33.33);
    return fract((p.x + p.y) * p.x);
}
void main() {
    vec2 uv = v_texcoord * 2.0 - 1.0;
    float r = length(uv);
    float angle = atan(uv.y, uv.x);
    float wave = 0.0;
    for (int i = 0; i < 8; i++) {
        float fi = float(i);
        float freq = 3.0 + fi * 2.0;
        float phase = u_time * (1.0 + fi * 0.3);
        wave += sin(angle * freq + phase) * 0.01 / (1.0 + fi * 0.5);
    }
    float ring = abs(r - u_scale + wave);
    float px = 1.0 / 500.0 * u_thickness;
    float alpha = 1.0 - smoothstep(0.0, px, ring);
    float glow = exp(-ring * 80.0 / u_thickness) * 0.4;
    alpha = clamp(alpha + glow, 0.0, 1.0);
    vec3 col = vec3(u_color_r, u_color_g, u_color_b);
    gl_FragColor = vec4(col * alpha, alpha * u_color_a);
}
