#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_width;
uniform float u_height;
uniform float u_dot_size;    // cell size in pixels (4-20)
uniform float u_color_mode;  // 0=mono, 1=cmyk

// Compute a single halftone dot layer at a given angle and ink value
float halftone_dot(vec2 pixel, float angle_deg, float ink) {
    float a = angle_deg * 3.14159 / 180.0;
    float ca = cos(a);
    float sa = sin(a);
    vec2 rotated = vec2(ca * pixel.x + sa * pixel.y,
                       -sa * pixel.x + ca * pixel.y);
    vec2 cell = mod(rotated, u_dot_size) / u_dot_size - 0.5;
    float dist = length(cell);
    float radius = ink * 0.7;  // darker = bigger dot
    return smoothstep(radius + 0.02, radius - 0.02, dist);
}

void main() {
    vec2 uv = v_texcoord;

    // Passthrough when dot_size is very small (disabled sentinel)
    if (u_dot_size < 1.0) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    vec4 src = texture2D(tex, uv);
    vec2 pixel = gl_FragCoord.xy;

    if (u_color_mode < 0.5) {
        // --- Monochrome halftone ---
        float lum = dot(src.rgb, vec3(0.299, 0.587, 0.114));
        float ink = 1.0 - lum;
        float d = halftone_dot(pixel, 45.0, ink);
        gl_FragColor = vec4(vec3(1.0 - d), 1.0);
    } else {
        // --- CMYK halftone with angle separation ---
        // RGB to CMY
        float c_ink = 1.0 - src.r;
        float m_ink = 1.0 - src.g;
        float y_ink = 1.0 - src.b;
        float k_ink = min(c_ink, min(m_ink, y_ink));

        // Under-color removal
        c_ink = (c_ink - k_ink) / (1.0 - k_ink + 0.001);
        m_ink = (m_ink - k_ink) / (1.0 - k_ink + 0.001);
        y_ink = (y_ink - k_ink) / (1.0 - k_ink + 0.001);

        // Each channel at its screen angle (C=15, M=75, Y=0, K=45)
        float c_dot = halftone_dot(pixel, 15.0, c_ink);
        float m_dot = halftone_dot(pixel, 75.0, m_ink);
        float y_dot = halftone_dot(pixel, 0.0,  y_ink);
        float k_dot = halftone_dot(pixel, 45.0, k_ink);

        // Subtractive color: start white, subtract ink layers
        vec3 color = vec3(1.0);
        color -= vec3(0.0, c_dot * 0.7, c_dot);        // cyan
        color -= vec3(m_dot, 0.0, m_dot * 0.3);        // magenta
        color -= vec3(y_dot * 0.1, y_dot * 0.1, y_dot); // yellow
        color -= vec3(k_dot);                           // black

        gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
    }
}
