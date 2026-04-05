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

    // --- Characteristic 4: Tracking artifacts — integrated rolling bands ---
    // Primary band — subtle displacement, noise blends with content
    float bandCenter = fract(t * 0.08 + 0.2);
    float bandDist = abs(uv.y - bandCenter);
    float bandWidth = 0.08;
    if (bandDist < bandWidth) {
        float bandInt = 1.0 - bandDist / bandWidth;
        bandInt = pow(bandInt, 1.5);
        // Per-line variation WITHIN the band — each line has its own character
        float lineChar = hash(vec2(line * 2.3, t * 1.7));
        float lineIntensity = bandInt * (0.4 + lineChar * 0.6);  // 40-100% per line
        // Displacement varies wildly per line
        float lineShift = hash(vec2(line * 0.3, t * 3.0));
        float disp = (lineShift - 0.5) * 45.0 * px * lineIntensity;
        uv.x += disp;
        // Some lines get more noise, some get brightness spikes
        float nr = hash(vec2(uv.x * 80.0, line + t * 17.0));
        float ng = hash(vec2(uv.x * 80.0 + 7.0, line + t * 23.0));
        float nb = hash(vec2(uv.x * 80.0 + 13.0, line + t * 31.0));
        trackingColor = vec3(nr, ng, nb) * 0.4;
        trackingMix = lineIntensity * 0.35;
        // Random bright flashes on some lines within the band
        if (lineChar > 0.85) trackingMix += 0.2;
    }
    // Secondary band — similar treatment
    float band2Center = fract(bandCenter + 0.4);
    float band2Dist = abs(v_texcoord.y - band2Center);
    if (band2Dist < 0.04) {
        float b2Int = 1.0 - band2Dist / 0.04;
        b2Int = pow(b2Int, 1.5);
        float b2LineChar = hash(vec2(line * 3.1, t * 2.3));
        float b2LineInt = b2Int * (0.3 + b2LineChar * 0.7);
        float b2Shift = (hash(vec2(line, t * 7.0)) - 0.5) * 25.0 * px * b2LineInt;
        uv.x += b2Shift;
        float b2n = hash(vec2(uv.x * 60.0, line + t * 11.0));
        trackingColor = vec3(b2n * 0.3, b2n * 0.15, b2n * 0.5);
        trackingMix = max(trackingMix, b2LineInt * 0.3);
        if (b2LineChar > 0.9) trackingMix += 0.15;
    }

    // --- Characteristic 3: Head-switching noise (bottom 5-8%) ---
    if (uv.y > u_head_switch_y) {
        float ln = hash(vec2(line, t * 7.0));
        uv.x += (ln - 0.5) * 80.0 * px;
        float headNoise = hash(vec2(line * 3.0, t * 11.0));
        uv.y += (headNoise - 0.5) * 0.003;
    }

    // --- Characteristic 2: Chroma bleed — HEAVY RGB separation ---
    float shift = u_chroma_shift * px * 6.0;
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

    // Per-line luminance noise
    float lineNoise = hash(vec2(line * 1.7, t * 0.5 + 42.0));
    color.rgb *= 0.82 + lineNoise * 0.36;

    // High-frequency snow/static
    float snow = hash(vec2(uv.x * u_width * 0.3, line + t * 40.0));
    color.rgb += (snow - 0.5) * 0.14;

    // --- Tape degradation ---
    float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    vec3 blurL = texture2D(tex, vec2(uv.x - 3.0 * px, uv.y)).rgb;
    vec3 blurR = texture2D(tex, vec2(uv.x + 3.0 * px, uv.y)).rgb;
    vec3 blurChroma = (blurL + blurR) * 0.5;
    float blurLum = dot(blurChroma, vec3(0.299, 0.587, 0.114));
    color.rgb = vec3(lum) + (blurChroma - vec3(blurLum)) * 0.6;

    // Cool blue/cyan VHS color cast
    color.rgb = mix(color.rgb, vec3(lum * 0.75, lum * 0.92, lum * 1.2), 0.3);

    // Contrast reduction
    color.rgb = mix(vec3(0.15), color.rgb, 0.82);

    gl_FragColor = clamp(color, 0.0, 1.0);
}
