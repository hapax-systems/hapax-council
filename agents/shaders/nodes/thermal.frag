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
uniform float u_intensity;      // 0-1, mix ratio of thermal over original (default 0.65)
uniform float u_palette;        // 0=ironbow, 1=cool, 2=warm

// --- Pseudo-random hash ---
float hash(vec2 p) {
    p = fract(p * vec2(0.1031, 0.1030));
    p += dot(p, p.yx + 33.33);
    return fract((p.x + p.y) * p.x);
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

// Cool palette: black -> dark blue -> cyan -> white
vec3 cool_palette(float t) {
    t = clamp(t, 0.0, 1.0);
    if (t < 0.33) return mix(vec3(0.0),             vec3(0.0, 0.0, 0.5),   t / 0.33);
    if (t < 0.66) return mix(vec3(0.0, 0.0, 0.5),   vec3(0.0, 0.8, 0.9),   (t - 0.33) / 0.33);
    return              mix(vec3(0.0, 0.8, 0.9),   vec3(1.0, 1.0, 1.0),   (t - 0.66) / 0.34);
}

// Warm palette: black -> dark red -> orange -> yellow -> white
vec3 warm_palette(float t) {
    t = clamp(t, 0.0, 1.0);
    if (t < 0.33) return mix(vec3(0.0),             vec3(0.6, 0.0, 0.0),   t / 0.33);
    if (t < 0.66) return mix(vec3(0.6, 0.0, 0.0),   vec3(1.0, 0.5, 0.0),   (t - 0.33) / 0.33);
    return              mix(vec3(1.0, 0.5, 0.0),   vec3(1.0, 1.0, 0.5),   (t - 0.66) / 0.34);
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
    vec3 color;
    if (u_palette > 1.5) {
        color = warm_palette(palIdx);
    } else if (u_palette > 0.5) {
        color = cool_palette(palIdx);
    } else {
        color = thermal_palette(palIdx);
    }

    // --- Hot-source bloom (bright regions glow outward) ---
    float bloom = smoothstep(0.7, 1.0, lum) * u_edge_glow * 0.4;
    color += bloom * vec3(1.0, 0.9, 0.7);

    // --- Low-frequency thermal noise ---
    float noise = hash(uv * 40.0 + vec2(u_time * 0.3, u_time * 0.2));
    noise = (noise - 0.5) * 0.04;
    color += noise;

    // --- Blend with original frame via screen blend ---
    // Screen mode: result = 1 - (1-orig)*(1-thermal*intensity).
    // Unlike linear mix, screen ADDS the thermal color on top of the
    // original rather than replacing dark areas with solid blue.
    // In dim scenes the original contributes less, so we also scale
    // the thermal intensity by the scene luminance to prevent the
    // false-color palette from overwhelming the base image.
    vec3 orig = texture2D(tex, v_texcoord).rgb;
    float mix_amt = clamp(u_intensity, 0.0, 1.0);
    // When u_intensity is 0.0 (uninitialised uniform), default to 0.35
    if (mix_amt < 0.001) mix_amt = 0.35;

    // Luminance-adaptive: reduce intensity in very dark scenes
    // so the thermal false-color doesn't swamp the feed.
    float scene_lum = dot(orig, vec3(0.299, 0.587, 0.114));
    float lum_gate = smoothstep(0.02, 0.15, scene_lum);
    mix_amt *= (0.3 + 0.7 * lum_gate);

    // Screen blend: thermal colors brighten the original instead of
    // replacing it. This preserves the base image in dark regions
    // while still showing the false-color overlay in brighter areas.
    vec3 thermal_scaled = clamp(color, 0.0, 1.0) * mix_amt;
    vec3 final_color = 1.0 - (1.0 - orig) * (1.0 - thermal_scaled);

    gl_FragColor = vec4(final_color, 1.0);
}
