#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_width;
uniform float u_height;
uniform float u_edge_glow;      // 0-1, Sobel edge brightness
uniform float u_palette_shift;  // 0-1, cycles palette offset

// --- Pseudo-random hash ---
float hash(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

// Ironbow palette: black -> blue -> purple -> red -> orange -> yellow -> white
vec3 thermal_palette(float t) {
    t = clamp(t, 0.0, 1.0);
    if (t < 0.15) return mix(vec3(0.0),             vec3(0.0, 0.0, 0.6),   t / 0.15);
    if (t < 0.30) return mix(vec3(0.0, 0.0, 0.6),   vec3(0.5, 0.0, 0.7),   (t - 0.15) / 0.15);
    if (t < 0.50) return mix(vec3(0.5, 0.0, 0.7),   vec3(0.9, 0.1, 0.1),   (t - 0.30) / 0.20);
    if (t < 0.65) return mix(vec3(0.9, 0.1, 0.1),   vec3(1.0, 0.5, 0.0),   (t - 0.50) / 0.15);
    if (t < 0.80) return mix(vec3(1.0, 0.5, 0.0),   vec3(1.0, 1.0, 0.0),   (t - 0.65) / 0.15);
    return              mix(vec3(1.0, 1.0, 0.0),   vec3(1.0, 1.0, 1.0),   (t - 0.80) / 0.20);
}

void main() {
    vec2 uv = v_texcoord;

    // Passthrough when edge_glow is negative (disabled sentinel)
    if (u_edge_glow < -0.5) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    // Reduce effective resolution to ~480x270 (thermal sensor simulation)
    vec2 quantRes = vec2(u_width, u_height) * 0.25;
    uv = floor(uv * quantRes) / quantRes;

    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);

    // --- 5x5 Gaussian blur (thermal sensor resolution simulation) ---
    float lum = 0.0;
    float totalWeight = 0.0;
    for (float dy = -2.0; dy <= 2.0; dy += 1.0) {
        for (float dx = -2.0; dx <= 2.0; dx += 1.0) {
            float w = exp(-(dx*dx + dy*dy) / 4.5);
            vec2 sampleUV = uv + vec2(dx, dy) * texel * 2.0;
            lum += dot(texture2D(tex, sampleUV).rgb, vec3(0.299, 0.587, 0.114)) * w;
            totalWeight += w;
        }
    }
    lum = lum / totalWeight;

    // --- Palette mapping with shift ---
    float palIdx = fract(lum + u_palette_shift);
    vec3 color = thermal_palette(palIdx);

    // --- Hot-source bloom (bright regions glow outward) ---
    float bloom = smoothstep(0.7, 1.0, lum) * u_edge_glow * 0.4;
    color += bloom * vec3(1.0, 0.9, 0.7);

    // --- Low-frequency thermal noise ---
    float noise = hash(uv * 40.0 + vec2(u_time * 0.3, u_time * 0.2));
    noise = (noise - 0.5) * 0.04;
    color += noise;

    gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
