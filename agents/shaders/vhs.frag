#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_chroma_shift;   // pixels of RGB offset (3-6)
uniform float u_head_switch_y;  // normalized y position of head switch band
uniform float u_noise_band_y;   // normalized y of scrolling noise band
uniform float u_width;          // texture width in pixels
uniform float u_height;         // texture height in pixels

void main() {
    vec2 uv = v_texcoord;
    float px = 1.0 / u_width;

    // Horizontal jitter in head switch region (bottom 8%)
    if (uv.y > 0.92) {
        float jitter = sin(u_time * 3.0 + uv.y * 50.0) * 8.0 * px;
        uv.x += jitter;
    }

    // RGB channel separation (chroma shift)
    float shift = u_chroma_shift * px;
    float r = texture2D(tex, vec2(uv.x - shift, uv.y)).r;
    float g = texture2D(tex, uv).g;
    float b = texture2D(tex, vec2(uv.x + shift, uv.y)).b;
    vec4 color = vec4(r, g, b, 1.0);

    // Sepia warmth
    float gray = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    vec3 sepia = vec3(gray * 1.15, gray * 1.0, gray * 0.85);
    color.rgb = mix(color.rgb, sepia, 0.45);

    // Slight blur simulation via neighbor averaging
    vec4 blur = texture2D(tex, uv + vec2(px, 0.0)) + texture2D(tex, uv - vec2(px, 0.0));
    color.rgb = mix(color.rgb, blur.rgb * 0.5, 0.15);

    // Contrast boost
    color.rgb = (color.rgb - 0.5) * 1.25 + 0.5;

    // Scrolling noise band
    float bandDist = abs(uv.y - u_noise_band_y);
    float bandWidth = 0.015;
    if (bandDist < bandWidth) {
        float noise = fract(sin(dot(uv * u_time, vec2(12.9898, 78.233))) * 43758.5453);
        color.rgb = mix(color.rgb, vec3(noise), 0.7);
    }

    // Scanlines
    float scanline = mod(gl_FragCoord.y, 4.0);
    if (scanline < 1.5) {
        color.rgb *= 0.88;
    }

    gl_FragColor = color;
}
