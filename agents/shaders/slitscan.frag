#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_width;
uniform float u_height;
uniform float u_scan_speed;   // 0.1-2.0, temporal scroll rate
uniform float u_scan_axis;    // 0=horizontal scan, 1=vertical scan
uniform float u_warp_amount;  // 0-1, horizontal distortion intensity

// Pseudo-random for subtle variation
float hash(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
    vec2 uv = v_texcoord;

    // Passthrough when scan_speed effectively zero
    if (u_scan_speed < 0.01) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    // Determine scan position (0=center of image, 1=edge)
    // Center samples "now", edges sample "older" via UV offset
    float scan_pos;
    if (u_scan_axis < 0.5) {
        // Horizontal scan: each row at different temporal phase
        scan_pos = abs(uv.y - 0.5) * 2.0;
    } else {
        // Vertical scan: each column at different temporal phase
        scan_pos = abs(uv.x - 0.5) * 2.0;
    }

    // Temporal displacement — rows/columns near edges get larger UV offset
    // This simulates sampling from different moments in time
    float phase = u_time * u_scan_speed;
    float displacement = scan_pos * scan_pos * 0.15;

    // Scrolling wave creates the continuously moving slit effect
    float wave = sin(phase + scan_pos * 6.2832) * 0.5 + 0.5;
    displacement *= (0.5 + wave * 0.5);

    // Apply displacement along the scan axis
    vec2 displaced_uv = uv;
    if (u_scan_axis < 0.5) {
        // Horizontal scan: displace X based on Y position
        displaced_uv.x += displacement * sign(uv.x - 0.5);
    } else {
        // Vertical scan: displace Y based on X position
        displaced_uv.y += displacement * sign(uv.y - 0.5);
    }

    // Horizontal warp — "pulled through time" distortion
    float warp = u_warp_amount * scan_pos;
    float warp_wave = sin(phase * 1.7 + uv.y * 12.0) * warp * 0.03;
    displaced_uv.x += warp_wave;

    // Secondary vertical ripple for organic feel
    float ripple = sin(phase * 0.8 + uv.x * 8.0) * warp * 0.015;
    displaced_uv.y += ripple;

    // Clamp to valid UV range
    displaced_uv = clamp(displaced_uv, 0.0, 1.0);

    // Sample with slight chromatic separation for temporal smear look
    float chroma_spread = displacement * 0.3 * u_warp_amount;
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);
    float r = texture2D(tex, displaced_uv + vec2(chroma_spread, 0.0) * texel * 3.0).r;
    float g = texture2D(tex, displaced_uv).g;
    float b = texture2D(tex, displaced_uv - vec2(chroma_spread, 0.0) * texel * 3.0).b;

    gl_FragColor = vec4(r, g, b, 1.0);
}
