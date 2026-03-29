#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
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
    float entry_offset = (1.0 - entry_progress) * 0.4;
    vec2 entry_dir = vec2(sin(u_time * 0.1 + 2.1), cos(u_time * 0.1 + 1.7));
    uv += entry_dir * entry_offset;

    vec4 color = texture2D(tex, uv);

    // Materialization
    float noise = hash21(v_texcoord * 30.0 + u_time * 0.05);
    float mat_factor = smoothstep(1.0 - u_salience, 1.0 - u_salience + 0.3, noise);
    color.rgb *= mat_factor;

    // Dwelling trace boost
    float trace_boost = 1.0 + (1.0 - smoothstep(0.3, 0.7, u_salience)) * 0.15;
    color.rgb *= trace_boost;

    gl_FragColor = color;
}
