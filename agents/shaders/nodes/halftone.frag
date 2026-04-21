#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_width;
uniform float u_height;
uniform float u_dot_size;
uniform float u_color_mode;  // 0=mono, 1=cmyk+lichtenstein

float halftone_dot(vec2 pixel, float angle_deg, float ink, float size) {
    float a = angle_deg * 3.14159 / 180.0;
    float ca = cos(a);
    float sa = sin(a);
    vec2 rotated = vec2(ca * pixel.x + sa * pixel.y,
                       -sa * pixel.x + ca * pixel.y);
    vec2 cell = mod(rotated, size) / size - 0.5;
    float dist = length(cell);
    float radius = sqrt(ink) * 0.5;
    return smoothstep(radius + 0.04, radius - 0.04, dist);
}

void main() {
    vec2 uv = v_texcoord;
    if (u_dot_size < 1.0) { gl_FragColor = texture2D(tex, uv); return; }

    vec4 src = texture2D(tex, uv);
    vec2 pixel = gl_FragCoord.xy;

    if (u_color_mode < 0.5) {
        // --- Monochrome ---
        float lum = dot(src.rgb, vec3(0.299, 0.587, 0.114));
        float d = halftone_dot(pixel, 45.0, 1.0 - lum, u_dot_size);
        gl_FragColor = vec4(vec3(1.0 - d), 1.0);
    } else {
        // --- CMYK + Lichtenstein bold color push ---

        // Step 1: Lichtenstein bold color push
        vec3 col = src.rgb;
        // Posterize first -- reduce to ~4 tonal levels (flat Lichtenstein regions)
        col = floor(col * 4.0 + 0.5) / 4.0;
        // Hypersaturate -- push toward pure primaries
        float gray = dot(col, vec3(0.333));
        col = mix(vec3(gray), col, 4.0);
        col = clamp(col, 0.0, 1.0);
        // Gamma lift for more visible dot variation in midtones
        col = pow(col, vec3(0.5));

        // Step 2: RGB to CMYK
        float c_ink = 1.0 - col.r;
        float m_ink = 1.0 - col.g;
        float y_ink = 1.0 - col.b;
        float k_ink = min(c_ink, min(m_ink, y_ink));

        // Under-color removal
        float div = 1.0 - k_ink + 0.001;
        c_ink = (c_ink - k_ink) / div;
        m_ink = (m_ink - k_ink) / div;
        y_ink = (y_ink - k_ink) / div;

        // Step 3: Each channel at its screen angle -- rosette emerges from overlap
        float c_dot = halftone_dot(pixel, 15.0, c_ink, u_dot_size);
        float m_dot = halftone_dot(pixel, 75.0, m_ink, u_dot_size);
        float y_dot = halftone_dot(pixel, 0.0,  y_ink, u_dot_size * 0.9);  // slightly smaller for moire
        float k_dot = halftone_dot(pixel, 45.0, k_ink, u_dot_size * 1.1);  // slightly larger

        // Step 4: Subtractive color on white substrate
        vec3 result = vec3(1.0);
        result.r -= c_dot * 0.9;   // cyan absorbs red
        result.g -= m_dot * 0.9;   // magenta absorbs green
        result.b -= y_dot * 0.85;  // yellow absorbs blue (lighter ink)
        result -= vec3(k_dot);     // black absorbs all

        gl_FragColor = vec4(clamp(result, 0.0, 1.0), 1.0);
    }
}
