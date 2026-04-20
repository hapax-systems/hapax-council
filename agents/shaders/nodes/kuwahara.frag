#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_radius;
uniform float u_width;
uniform float u_height;

// Kuwahara filter: edge-preserving painterly blur.
// Divides a square neighbourhood into 4 quadrants around each pixel,
// computes mean + variance of each, selects the quadrant with the
// lowest variance and outputs its mean. Preserves edges, smooths
// interior, gives a poster-paint appearance that still reads as the
// source image.

void main() {
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);
    float r = max(1.0, floor(u_radius));

    vec3 mean[4];
    vec3 var4[4];
    for (int q = 0; q < 4; q++) {
        mean[q] = vec3(0.0);
        var4[q] = vec3(0.0);
    }

    // Offsets for the 4 overlapping quadrants: TL, TR, BL, BR.
    vec2 off[4];
    off[0] = vec2(-r, -r);
    off[1] = vec2(0.0, -r);
    off[2] = vec2(-r, 0.0);
    off[3] = vec2(0.0, 0.0);

    // Each quadrant has (r+1)x(r+1) samples when centred pixel is shared.
    float count = (r + 1.0) * (r + 1.0);

    for (int q = 0; q < 4; q++) {
        vec3 sum = vec3(0.0);
        vec3 sumSq = vec3(0.0);
        for (float i = 0.0; i <= 8.0; i += 1.0) {
            if (i > r) break;
            for (float j = 0.0; j <= 8.0; j += 1.0) {
                if (j > r) break;
                vec2 s = v_texcoord + (off[q] + vec2(i, j)) * texel;
                vec3 c = texture2D(tex, s).rgb;
                sum += c;
                sumSq += c * c;
            }
        }
        mean[q] = sum / count;
        var4[q] = sumSq / count - mean[q] * mean[q];
    }

    // Pick the quadrant with minimum total variance.
    vec3 minV = var4[0];
    vec3 outColor = mean[0];
    for (int q = 1; q < 4; q++) {
        float totalV = var4[q].r + var4[q].g + var4[q].b;
        float minTotalV = minV.r + minV.g + minV.b;
        if (totalV < minTotalV) {
            minV = var4[q];
            outColor = mean[q];
        }
    }

    gl_FragColor = vec4(outColor, texture2D(tex, v_texcoord).a);
}
