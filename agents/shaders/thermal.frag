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

    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);

    // --- Luminance with slight temporal smoothing (sensor lag) ---
    float lum = dot(texture2D(tex, uv).rgb, vec3(0.299, 0.587, 0.114));

    // Slight blur to simulate lower thermal sensor resolution
    float lumL = dot(texture2D(tex, uv + vec2(-texel.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lumR = dot(texture2D(tex, uv + vec2( texel.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lumU = dot(texture2D(tex, uv + vec2(0.0,  texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    float lumD = dot(texture2D(tex, uv + vec2(0.0, -texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    lum = (lum * 0.4 + (lumL + lumR + lumU + lumD) * 0.15);

    // --- Sobel edge detection ---
    float tl = dot(texture2D(tex, uv + vec2(-texel.x,  texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    float tr = dot(texture2D(tex, uv + vec2( texel.x,  texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    float ml = lumL;
    float mr = lumR;
    float bl = dot(texture2D(tex, uv + vec2(-texel.x, -texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    float br = dot(texture2D(tex, uv + vec2( texel.x, -texel.y)).rgb, vec3(0.299, 0.587, 0.114));

    float gx = -tl - 2.0 * ml - bl + tr + 2.0 * mr + br;
    float gy = -tl - 2.0 * lumU - tr + bl + 2.0 * lumD + br;
    float edge = sqrt(gx * gx + gy * gy);

    // --- Palette mapping with shift ---
    float palIdx = fract(lum + u_palette_shift);
    vec3 color = thermal_palette(palIdx);

    // --- Edge glow (warm white/yellow at edges like heat radiation) ---
    color += edge * u_edge_glow * 2.0 * vec3(1.0, 0.85, 0.3);

    // --- Low-frequency thermal noise ---
    float noise = hash(uv * 40.0 + vec2(u_time * 0.3, u_time * 0.2));
    noise = (noise - 0.5) * 0.04;
    color += noise;

    gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
