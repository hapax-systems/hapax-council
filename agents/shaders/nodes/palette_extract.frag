#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_swatch_count;
uniform float u_strip_height;
uniform float u_strip_opacity;
uniform float u_width;
uniform float u_height;

// Palette extract: samples the frame on a coarse grid, displays the per-
// column mean as a horizontal swatch strip along the bottom N% of the
// output. Not true K-means (no shared memory in fragment pipelines),
// but cheap and serves the contextualization move — shows which colors
// dominate the cover without replacing it.
//
// Non-strip pixels: pass-through (source unchanged). Strip region:
// render the dominant swatch for that horizontal position, alpha-
// blended at u_strip_opacity.

const float SAMPLE_ROWS = 8.0;  // vertical samples per swatch column

vec3 sample_column_mean(float col_u0, float col_u1) {
    // Average SAMPLE_ROWS sample rows per column, each row 4 samples wide.
    vec3 sum = vec3(0.0);
    float count = 0.0;
    for (float r = 0.0; r < SAMPLE_ROWS; r += 1.0) {
        float v = (r + 0.5) / SAMPLE_ROWS;
        for (float c = 0.0; c < 4.0; c += 1.0) {
            float u = mix(col_u0, col_u1, (c + 0.5) / 4.0);
            sum += texture2D(tex, vec2(u, v)).rgb;
            count += 1.0;
        }
    }
    return sum / count;
}

void main() {
    vec4 source = texture2D(tex, v_texcoord);

    float y = v_texcoord.y;
    if (y > u_strip_height) {
        // Pass-through: source pixel, unchanged.
        gl_FragColor = source;
        return;
    }

    // In the strip. Determine which swatch column this pixel belongs to.
    float count = max(3.0, floor(u_swatch_count));
    float idx = floor(v_texcoord.x * count);
    idx = clamp(idx, 0.0, count - 1.0);
    float u0 = idx / count;
    float u1 = (idx + 1.0) / count;

    vec3 swatch = sample_column_mean(u0, u1);
    vec3 blended = mix(source.rgb, swatch, u_strip_opacity);
    gl_FragColor = vec4(blended, 1.0);
}
