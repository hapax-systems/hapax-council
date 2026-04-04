#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_width;
uniform float u_height;
uniform float u_block_size;  // block size in pixels (8-64)
uniform float u_intensity;   // corruption probability (0-1)
uniform float u_rgb_split;   // chromatic aberration amount (0-1)

// --- Per-block hash (integer-style, no sin precision issues) ---
float blockHash(vec2 blockID, float seed) {
    vec3 p3 = fract(vec3((blockID + seed).xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 19.19);
    return fract((p3.x + p3.y) * p3.z);
}

void main() {
    vec2 uv = v_texcoord;

    // Passthrough when intensity is zero
    if (u_intensity < 0.01) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    vec2 pixel = gl_FragCoord.xy;
    vec2 blockID = floor(pixel / u_block_size);

    // Time slot: blocks persist for 3-8 frames (~0.1-0.3s at 25fps)
    // Use floor to quantize time so blocks don't flicker every frame
    float timeSlot = floor(u_time * 5.0);

    // Base corruption decision
    float h = blockHash(blockID, timeSlot);
    float corruptThreshold = u_intensity * 0.4;  // scale so 1.0 isn't 100% corrupt

    if (h < corruptThreshold) {
        // --- This block is corrupted ---
        float effectType = blockHash(blockID, timeSlot + 10.0);

        if (effectType < 0.4) {
            // Displacement: shift the block's UV
            float shiftX = (blockHash(blockID, timeSlot + 1.0) - 0.5) * 60.0 / u_width;
            float shiftY = (blockHash(blockID, timeSlot + 2.0) - 0.5) * 6.0 / u_height;
            vec2 displaced = uv + vec2(shiftX, shiftY) * u_intensity;

            // RGB channel split
            float split = u_rgb_split * blockHash(blockID, timeSlot + 3.0) * 8.0 / u_width;
            float r = texture2D(tex, displaced + vec2(split, 0.0)).r;
            float g = texture2D(tex, displaced).g;
            float b = texture2D(tex, displaced - vec2(split, 0.0)).b;
            gl_FragColor = vec4(r, g, b, 1.0);

        } else if (effectType < 0.55) {
            // Brightness corruption + posterization
            vec4 color = texture2D(tex, uv);
            float bright = blockHash(blockID, timeSlot + 4.0) * 2.0;
            color.rgb *= bright;
            color.rgb = floor(color.rgb * 4.0) / 4.0;
            gl_FragColor = clamp(color, 0.0, 1.0);

        } else if (effectType < 0.85) {
            // Color channel swap
            vec4 color = texture2D(tex, uv);
            float swapSeed = blockHash(blockID, timeSlot + 5.0);
            if (swapSeed < 0.33)
                gl_FragColor = vec4(color.b, color.r, color.g, 1.0);
            else if (swapSeed < 0.66)
                gl_FragColor = vec4(color.g, color.b, color.r, 1.0);
            else
                gl_FragColor = vec4(color.r, color.b, color.g, 1.0);

        } else if (effectType < 0.9) {
            // Solid block (dead pixel block)
            float v = blockHash(blockID, timeSlot + 6.0);
            gl_FragColor = vec4(vec3(v * 0.3), 1.0);
        } else {
            // Data pattern bleed
            vec2 pixel = gl_FragCoord.xy;
            float pattern = mod(pixel.x + pixel.y * 3.0, 8.0) / 8.0;
            float patternR = mod(pixel.x * 2.0 + pixel.y, 6.0) / 6.0;
            gl_FragColor = vec4(pattern, patternR * 0.7, pattern * 0.5, 1.0);
        }
    } else {
        // --- Clean block ---
        gl_FragColor = texture2D(tex, uv);
    }
}
