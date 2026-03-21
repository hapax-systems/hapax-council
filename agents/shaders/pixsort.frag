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

// --- Luminance ---
float luma(vec3 c) {
    return dot(c, vec3(0.299, 0.587, 0.114));
}

void main() {
    vec2 uv = v_texcoord;

    // Passthrough when sort_length disabled
    if (u_sort_length < 1.0) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    vec4 orig = texture2D(tex, uv);
    float lum = luma(orig.rgb);

    // Only sort pixels within threshold window
    if (lum < u_threshold_low || lum > u_threshold_high) {
        gl_FragColor = orig;
        return;
    }

    // Sort direction from u_direction: 0=right, 0.5=diagonal, 1=down
    float angle = u_direction * 3.14159 * 0.5;
    vec2 dir = vec2(cos(angle), sin(angle));
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);

    vec3 accum = vec3(0.0);
    float weight = 0.0;
    float len = min(u_sort_length, 64.0);

    // Sample neighbors along sort direction, accumulate weighted average
    for (float i = 0.0; i < 64.0; i += 1.0) {
        if (i >= len) break;
        vec2 sampleUV = uv + dir * texel * i;

        // Clamp to texture bounds
        if (sampleUV.x < 0.0 || sampleUV.x > 1.0 ||
            sampleUV.y < 0.0 || sampleUV.y > 1.0) break;

        vec4 s = texture2D(tex, sampleUV);
        float sLum = luma(s.rgb);

        // Stop at threshold boundary — dark regions anchor
        if (sLum < u_threshold_low || sLum > u_threshold_high) break;

        // Distance falloff — nearer samples weigh more
        float w = 1.0 - (i / len);
        w *= w;  // quadratic falloff for sharper streaks
        accum += s.rgb * w;
        weight += w;
    }

    // Also sample backwards (negative direction) for symmetry
    for (float i = 1.0; i < 64.0; i += 1.0) {
        if (i >= len * 0.5) break;
        vec2 sampleUV = uv - dir * texel * i;
        if (sampleUV.x < 0.0 || sampleUV.x > 1.0 ||
            sampleUV.y < 0.0 || sampleUV.y > 1.0) break;

        vec4 s = texture2D(tex, sampleUV);
        float sLum = luma(s.rgb);
        if (sLum < u_threshold_low || sLum > u_threshold_high) break;

        float w = 1.0 - (i / len);
        w *= w * 0.5;  // backwards samples weigh less
        accum += s.rgb * w;
        weight += w;
    }

    vec3 sorted = (weight > 0.0) ? accum / weight : orig.rgb;

    // Luminance-biased ordering: brighter pixels push toward sort direction
    // This mimics the visual gradient of true sorting
    float bias = smoothstep(u_threshold_low, u_threshold_high, lum);
    sorted = mix(sorted, sorted * (0.9 + 0.2 * bias), 0.5);

    gl_FragColor = vec4(sorted, 1.0);
}
