#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_speed;
uniform float u_amplitude;
uniform float u_frequency;
uniform float u_coherence;
uniform float u_time;
uniform float u_width;
uniform float u_height;

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

void main() {
    vec2 uv = v_texcoord;
    float t = u_time * u_speed;
    // layered noise displacement
    float n1 = noise(uv * u_frequency + t);
    float n2 = noise(uv * u_frequency * 2.0 + t * 1.3);
    float n3 = noise(uv * u_frequency * 0.5 + t * 0.7);
    float dx = mix(n1, (n1 + n2 * 0.5 + n3 * 0.25) / 1.75, u_coherence) - 0.5;
    float dy = mix(n2, (n2 + n3 * 0.5 + n1 * 0.25) / 1.75, u_coherence) - 0.5;
    vec2 offset = vec2(dx, dy) * u_amplitude * 0.1;
    gl_FragColor = texture2D(tex, uv + offset);
}
