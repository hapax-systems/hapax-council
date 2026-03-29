#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D content_slot_0;
uniform sampler2D content_slot_1;
uniform sampler2D content_slot_2;
uniform sampler2D content_slot_3;
uniform float u_salience;
uniform float u_intensity;
uniform float u_material;
uniform float u_time;

float hash21(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.547);
}

void main() {
    vec2 uv = v_texcoord;

    // Corner incubation
    float corner_offset = (1.0 - u_intensity) * 0.3;
    uv += (uv - 0.5) * corner_offset;

    // Immensity entry
    float entry_progress = smoothstep(0.0, 0.5, u_salience);
    uv += vec2(sin(u_time * 0.1 + 2.1), cos(u_time * 0.1 + 1.7)) * (1.0 - entry_progress) * 0.4;

    // Procedural background at original UV
    vec3 base = texture2D(tex, v_texcoord).rgb;

    // Blend slot 0 (simplified — full version in WGSL)
    vec4 c0 = texture2D(content_slot_0, uv);
    float noise = hash21(v_texcoord * 30.0 + u_time * 0.05);
    float mat_factor = smoothstep(1.0 - u_salience, 1.0 - u_salience + 0.3, noise);
    vec3 weighted = c0.rgb * mat_factor * u_salience;
    base = 1.0 - (1.0 - base) * (1.0 - weighted);

    // Dwelling trace boost
    float trace_boost = 1.0 + (1.0 - smoothstep(0.3, 0.7, u_salience)) * 0.15;
    base *= trace_boost;

    gl_FragColor = vec4(base, 1.0);
}
