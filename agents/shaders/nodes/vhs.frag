#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_chroma_shift;
uniform float u_head_switch_y;
uniform float u_noise_band_y;
uniform float u_width;
uniform float u_height;

float hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 19.19);
    return fract((p3.x + p3.y) * p3.z);
}

void main() {
    vec2 uv = v_texcoord;
    if (u_chroma_shift < 0.01) { gl_FragColor = texture2D(tex, uv); return; }

    float t = mod(u_time, 60.0);
    float px = 1.0 / max(u_width, 1.0);
    float line = floor(uv.y * max(u_height, 1.0));
    float trackingMix = 0.0;  // how much tracking corruption to blend
    vec3 trackingColor = vec3(0.0);

    // --- Characteristic 4: Multiple thin tracking bands ---
    // 5 bands at different speeds/positions, each thin (2-3%) with per-line dynamism
    for (int bi = 0; bi < 5; bi++) {
        float bSpeed = 0.05 + float(bi) * 0.03;
        float bOffset = float(bi) * 0.19 + 0.1;
        float bCenter = fract(t * bSpeed + bOffset);
        float bDist = abs(uv.y - bCenter);
        float bWidth = 0.015 + float(bi) * 0.005;  // 1.5% to 4% each
        if (bDist < bWidth) {
            float bInt = 1.0 - bDist / bWidth;
            bInt = pow(bInt, 1.5);
            // Per-line variation — each line has its own character
            float lineChar = hash(vec2(line * 2.3 + float(bi) * 7.0, t * 1.7));
            float lineIntensity = bInt * (0.4 + lineChar * 0.6);
            // Displacement varies per line
            float lineShift = hash(vec2(line * 0.3, t * 3.0 + float(bi) * 5.0));
            float disp = (lineShift - 0.5) * 35.0 * px * lineIntensity;
            uv.x += disp;
            // Color noise — tints content
            float nr = hash(vec2(uv.x * 80.0, line + t * 17.0 + float(bi) * 3.0));
            float ng = hash(vec2(uv.x * 80.0 + 7.0, line + t * 23.0 + float(bi)));
            float nb = hash(vec2(uv.x * 80.0 + 13.0, line + t * 31.0 + float(bi)));
            trackingColor = max(trackingColor, vec3(nr, ng, nb) * 0.35);
            trackingMix = max(trackingMix, lineIntensity * 0.3);
            if (lineChar > 0.85) trackingMix = min(trackingMix + 0.15, 0.55);
        }
    }

    // --- Characteristic 3: Head-switching noise (bottom 5-8%) ---
    if (uv.y > u_head_switch_y) {
        float ln = hash(vec2(line, t * 7.0));
        uv.x += (ln - 0.5) * 80.0 * px;
        float headNoise = hash(vec2(line * 3.0, t * 11.0));
        uv.y += (headNoise - 0.5) * 0.003;
    }

    // --- Characteristic 2: Chroma bleed — HEAVY RGB separation ---
    float shift = u_chroma_shift * px * 1.5;  // ~9px — subtle edge fringing only
    float r = texture2D(tex, vec2(uv.x + shift, uv.y)).r;
    float g = texture2D(tex, uv).g;
    float b = texture2D(tex, vec2(uv.x - shift, uv.y)).b;
    vec4 color = vec4(r, g, b, 1.0);

    // Apply tracking corruption ON TOP of chroma-separated content
    color.rgb = mix(color.rgb, trackingColor, trackingMix);
    color.rgb += vec3(trackingMix * 0.1);  // brightness boost in band

    // --- Characteristic 1: Refined horizontal scanlines + noise ---
    // Visible individual scanlines — ALWAYS applied, including in tracking bands
    float scanY = mod(gl_FragCoord.y, 3.0);
    float scanMask = smoothstep(0.0, 0.5, scanY) * smoothstep(3.0, 2.5, scanY);
    color.rgb *= mix(0.65, 1.0, scanMask);

    // Per-line luminance noise — denser (ref: wedding tape static)
    float lineNoise = hash(vec2(line * 1.7, t * 0.5 + 42.0));
    color.rgb *= 0.75 + lineNoise * 0.50;  // stronger per-line variation

    // High-frequency snow/static — heavier
    float snow = hash(vec2(uv.x * u_width * 0.5, line + t * 40.0));
    color.rgb += (snow - 0.5) * 0.20;

    // Per-pixel noise shimmer (extra density)
    float pixNoise = hash(vec2(gl_FragCoord.x * 0.7, gl_FragCoord.y + t * 60.0));
    color.rgb += (pixNoise - 0.5) * 0.06;

    // --- Tape degradation ---
    float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));

    // Soft cyan/teal color wash (ref: Boards of Canada — underwater feel)
    color.rgb = mix(color.rgb, vec3(lum * 0.7, lum * 1.0, lum * 1.2), 0.25);

    // Slight warmth in shadows (tape aging)
    color.r += (1.0 - lum) * 0.04;

    // Contrast reduction + lifted blacks (washed out look)
    color.rgb = mix(vec3(0.08), color.rgb, 0.85);

    gl_FragColor = clamp(color, 0.0, 1.0);
}
