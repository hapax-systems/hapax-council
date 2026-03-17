#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_vignette_strength;  // 0=none, 0.5=moderate, 1.0=heavy
uniform float u_scanline_alpha;     // 0=none, 0.12=subtle, 0.3=heavy
uniform float u_time;

// Band displacement
uniform float u_band_active;        // 1.0 if a band should displace this frame
uniform float u_band_y;             // normalized y of band center
uniform float u_band_height;        // normalized height
uniform float u_band_shift;         // normalized x shift

// Syrup gradient
uniform float u_syrup_active;
uniform float u_syrup_color_r;
uniform float u_syrup_color_g;
uniform float u_syrup_color_b;

void main() {
    vec2 uv = v_texcoord;

    // Band displacement
    if (u_band_active > 0.5) {
        float dist = abs(uv.y - u_band_y);
        if (dist < u_band_height * 0.5) {
            // Softer band edges
            float edgeFade = smoothstep(0.0, u_band_height * 0.5, u_band_height * 0.5 - dist);
            uv.x += u_band_shift * edgeFade;
        }
    }

    vec4 color = texture2D(tex, uv);

    // Gaussian-profile scanlines (replaces hard-threshold)
    if (u_scanline_alpha > 0.0) {
        float scanPos = mod(gl_FragCoord.y, 4.0);
        // Cosine profile: bright at scanline center, dark in gaps
        float scanBright = 0.5 + 0.5 * cos(scanPos * 3.14159 / 2.0);
        // Bright content bleeds into gaps (phosphor glow simulation)
        float localBright = dot(color.rgb, vec3(0.299, 0.587, 0.114));
        float gapFill = localBright * 0.25;
        float scanMult = mix(1.0 - u_scanline_alpha + gapFill, 1.0, scanBright);
        color.rgb *= scanMult;
    }

    // Vignette — slightly elliptical for 16:9
    if (u_vignette_strength > 0.0) {
        vec2 center = v_texcoord - 0.5;
        // Elliptical: less vignette on horizontal edges, more in corners
        center.x *= 0.85;
        float dist = length(center) * 1.5;
        float vig = 1.0 - smoothstep(0.3, 1.0, dist) * u_vignette_strength;
        color.rgb *= vig;
    }

    // Syrup gradient (darkens toward bottom)
    if (u_syrup_active > 0.5) {
        float gradStrength = smoothstep(0.3, 1.0, v_texcoord.y) * 0.25;
        color.rgb = mix(color.rgb, vec3(u_syrup_color_r, u_syrup_color_g, u_syrup_color_b), gradStrength);
    }

    gl_FragColor = color;
}
