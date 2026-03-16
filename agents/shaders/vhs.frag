#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_chroma_shift;   // pixels of RGB offset (3-6), 0=passthrough
uniform float u_head_switch_y;  // normalized y position of head switch band
uniform float u_noise_band_y;   // normalized y of scrolling noise band
uniform float u_width;          // texture width in pixels
uniform float u_height;         // texture height in pixels

// --- Pseudo-random hash ---
float hash(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
    vec2 uv = v_texcoord;

    // When chroma_shift is 0, this shader is a pure passthrough.
    // This is critical — non-VHS presets must not get VHS artifacts.
    if (u_chroma_shift < 0.01) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    float px = 1.0 / u_width;

    // --- Head-switching noise (bottom 6-8 lines) ---
    if (uv.y > 0.93) {
        float lineNoise = hash(vec2(floor(uv.y * u_height), u_time));
        float jitter = (lineNoise - 0.5) * 20.0 * px;
        uv.x += jitter;
    }

    // --- Chroma bandwidth simulation ---
    float luma = dot(texture2D(tex, uv).rgb, vec3(0.299, 0.587, 0.114));

    vec3 chromaSum = vec3(0.0);
    float chromaWeightTotal = 0.0;
    for (float i = -2.0; i <= 6.0; i += 1.0) {
        float weight = exp(-i * i / 8.0);
        float offset = (i + 1.0) * u_chroma_shift * 0.5 * px;
        vec3 s = texture2D(tex, vec2(uv.x + offset, uv.y)).rgb;
        float sLuma = dot(s, vec3(0.299, 0.587, 0.114));
        chromaSum += (s - sLuma) * weight;
        chromaWeightTotal += weight;
    }
    vec3 chroma = chromaSum / chromaWeightTotal;
    vec4 color = vec4(vec3(luma) + chroma, 1.0);

    // --- Composite video crosstalk ---
    float subcarrier = sin(uv.x * u_width * 3.14159 * 2.0 / 4.0 + uv.y * u_height * 0.5 + u_time * 2.0);
    float edgeDetect = abs(
        dot(texture2D(tex, uv + vec2(px, 0.0)).rgb, vec3(0.299, 0.587, 0.114)) -
        dot(texture2D(tex, uv - vec2(px, 0.0)).rgb, vec3(0.299, 0.587, 0.114))
    );
    float crosstalk = subcarrier * edgeDetect * 0.15;
    color.r += crosstalk;
    color.b -= crosstalk;

    // Head-switch brightness shift
    if (uv.y > 0.93) {
        float brightShift = hash(vec2(u_time, floor(uv.y * u_height))) * 0.3 - 0.15;
        color.rgb += brightShift;
    }

    // --- Sepia warmth ---
    float gray = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    vec3 sepia = vec3(gray * 1.15, gray * 1.0, gray * 0.85);
    color.rgb = mix(color.rgb, sepia, 0.35);

    // --- Slight blur (tape degradation) ---
    vec4 blur = texture2D(tex, uv + vec2(px, 0.0)) + texture2D(tex, uv - vec2(px, 0.0));
    color.rgb = mix(color.rgb, blur.rgb * 0.5, 0.1);

    // --- Contrast boost ---
    color.rgb = (color.rgb - 0.5) * 1.2 + 0.5;

    // --- Scrolling noise band ---
    float bandDist = abs(uv.y - u_noise_band_y);
    float bandWidth = 0.012;
    if (bandDist < bandWidth) {
        float noise = hash(uv * u_time * 100.0);
        float bandIntensity = 1.0 - (bandDist / bandWidth);
        color.rgb = mix(color.rgb, vec3(noise), 0.6 * bandIntensity);
    }

    // --- Gaussian-profile scanlines ---
    float scanPos = mod(gl_FragCoord.y, 4.0);
    float scanBright = 0.5 + 0.5 * cos(scanPos * 3.14159 / 2.0);
    float localBright = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    float gapFill = localBright * 0.3;
    float scanMult = mix(0.82 + gapFill, 1.0, scanBright);
    color.rgb *= scanMult;

    gl_FragColor = clamp(color, 0.0, 1.0);
}
