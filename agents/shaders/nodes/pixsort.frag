#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_width;
uniform float u_height;
uniform float u_threshold_low;   // 0-1, brightness gate low
uniform float u_threshold_high;  // 0-1, brightness gate high
uniform float u_sort_length;     // max samples (10-64), passthrough < 1
uniform float u_direction;       // 0=horizontal, 1=vertical, 0.5=diagonal

float luma(vec3 c) {
    return dot(c, vec3(0.299, 0.587, 0.114));
}

void main() {
    vec2 uv = v_texcoord;

    if (u_sort_length < 1.0) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    vec4 orig = texture2D(tex, uv);
    float lum = luma(orig.rgb);

    if (lum < u_threshold_low || lum > u_threshold_high) {
        gl_FragColor = orig;
        return;
    }

    float angle = u_direction * 3.14159 * 0.5;
    vec2 dir = vec2(cos(angle), sin(angle));
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);

    // Walk backward — capped at 64 (was 256)
    int intervalStart = 0;
    for (int i = 1; i < 64; i++) {
        vec2 sUV = uv - dir * texel * float(i);
        if (sUV.x < 0.0 || sUV.x > 1.0 || sUV.y < 0.0 || sUV.y > 1.0) break;
        float sLum = luma(texture2D(tex, sUV).rgb);
        if (sLum < u_threshold_low || sLum > u_threshold_high) break;
        intervalStart = i;
    }

    // Walk forward — capped at 64 (was 256)
    int intervalEnd = 0;
    for (int i = 1; i < 64; i++) {
        vec2 sUV = uv + dir * texel * float(i);
        if (sUV.x < 0.0 || sUV.x > 1.0 || sUV.y < 0.0 || sUV.y > 1.0) break;
        float sLum = luma(texture2D(tex, sUV).rgb);
        if (sLum < u_threshold_low || sLum > u_threshold_high) break;
        intervalEnd = i;
    }

    int intervalLen = intervalStart + intervalEnd + 1;
    if (intervalLen < 3) {
        gl_FragColor = orig;
        return;
    }

    // Sample 12 pixels (was 32) — 4x fewer sort iterations
    vec3 samples[12];
    float sampleLums[12];
    float stepSize = float(intervalLen) / 12.0;

    for (int i = 0; i < 12; i++) {
        float pos = -float(intervalStart) + stepSize * float(i);
        vec2 sUV = uv + dir * texel * pos;
        sUV = clamp(sUV, vec2(0.0), vec2(1.0));
        samples[i] = texture2D(tex, sUV).rgb;
        sampleLums[i] = luma(samples[i]);
    }

    // Bubble sort 12 samples (11x11=121 iterations vs 31x31=961)
    for (int pass = 0; pass < 11; pass++) {
        for (int j = 0; j < 11; j++) {
            if (j >= 11 - pass) break;
            if (sampleLums[j] > sampleLums[j + 1]) {
                vec3 tmpC = samples[j];
                samples[j] = samples[j + 1];
                samples[j + 1] = tmpC;
                float tmpL = sampleLums[j];
                sampleLums[j] = sampleLums[j + 1];
                sampleLums[j + 1] = tmpL;
            }
        }
    }

    float posInInterval = float(intervalStart) / float(intervalLen);
    float idx = posInInterval * 11.0;
    int idxLow = int(floor(idx));
    int idxHigh = int(ceil(idx));
    if (idxHigh > 11) idxHigh = 11;
    if (idxLow < 0) idxLow = 0;
    float frac = idx - float(idxLow);

    vec3 valLow = samples[0];
    vec3 valHigh = samples[0];
    for (int k = 0; k < 12; k++) {
        if (k == idxLow) valLow = samples[k];
        if (k == idxHigh) valHigh = samples[k];
    }

    vec3 sorted = mix(valLow, valHigh, frac);
    gl_FragColor = vec4(sorted, 1.0);
}
