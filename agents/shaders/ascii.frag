#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_width;
uniform float u_height;
uniform float u_cell_size;   // 4-16, passthrough < 2
uniform float u_color_mode;  // 0=green monochrome, 1=source color

// Procedural character density: returns 1.0 if pixel should be "on"
// based on luminance level and position within a 4x6 cell.
// Uses threshold-based fill patterns that increase density with luminance.
float charFill(float lum, vec2 cellPos) {
    // cellPos: 0-1 within the cell
    float cx = cellPos.x;
    float cy = cellPos.y;

    // Distance from cell center
    float dx = cx - 0.5;
    float dy = cy - 0.5;
    float d = sqrt(dx * dx + dy * dy);

    // Thresholds create increasingly filled patterns
    // Low lum = few pixels lit, high lum = many pixels lit
    if (lum < 0.05) return 0.0;  // space — nothing

    // Single center dot
    if (lum < 0.15) {
        return (d < 0.15) ? 1.0 : 0.0;
    }
    // Small center dot
    if (lum < 0.25) {
        return (d < 0.22) ? 1.0 : 0.0;
    }
    // Horizontal bar
    if (lum < 0.35) {
        return (abs(dy) < 0.12 && abs(dx) < 0.35) ? 1.0 : 0.0;
    }
    // Cross shape
    if (lum < 0.45) {
        float cross = min(abs(dx), abs(dy));
        return (cross < 0.15) ? 1.0 : 0.0;
    }
    // Diamond
    if (lum < 0.55) {
        return (abs(dx) + abs(dy) < 0.4) ? 1.0 : 0.0;
    }
    // Circle
    if (lum < 0.65) {
        return (d < 0.35) ? 1.0 : 0.0;
    }
    // Square
    if (lum < 0.75) {
        return (abs(dx) < 0.35 && abs(dy) < 0.35) ? 1.0 : 0.0;
    }
    // Large filled circle
    if (lum < 0.85) {
        return (d < 0.45) ? 1.0 : 0.0;
    }
    // Nearly full block
    if (lum < 0.95) {
        return (abs(dx) < 0.45 && abs(dy) < 0.45) ? 1.0 : 0.0;
    }
    // Full block
    return 1.0;
}

void main() {
    vec2 uv = v_texcoord;

    // Passthrough when cell_size too small
    if (u_cell_size < 2.0) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    float cellW = floor(u_cell_size);
    float cellH = floor(u_cell_size * 1.5);  // ~8x12 aspect for chars

    // Pixel coordinate
    vec2 pixel = vec2(uv.x * u_width, uv.y * u_height);

    // Cell index
    vec2 cellIdx = floor(pixel / vec2(cellW, cellH));

    // Cell center UV for color sampling
    vec2 cellCenter = (cellIdx + 0.5) * vec2(cellW, cellH);
    vec2 centerUV = cellCenter / vec2(u_width, u_height);

    // Average luminance of cell (multi-sample for smoother result)
    vec3 centerColor = texture2D(tex, centerUV).rgb;
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);
    vec3 c2 = texture2D(tex, centerUV + texel * vec2(-1.0, -1.0)).rgb;
    vec3 c3 = texture2D(tex, centerUV + texel * vec2(1.0, 1.0)).rgb;
    float lum = dot(centerColor * 0.5 + c2 * 0.25 + c3 * 0.25, vec3(0.299, 0.587, 0.114));

    // Position within cell normalized to 0-1
    vec2 posInCell = mod(pixel, vec2(cellW, cellH)) / vec2(cellW, cellH);

    float bit = charFill(lum, posInCell);

    // Foreground color
    vec3 fgColor;
    if (u_color_mode < 0.5) {
        fgColor = vec3(0.2, 1.0, 0.3);  // classic green terminal
    } else {
        fgColor = centerColor;
    }

    vec3 bgColor = vec3(0.02, 0.02, 0.02);
    vec3 color = mix(bgColor, fgColor, bit);

    gl_FragColor = vec4(color, 1.0);
}
