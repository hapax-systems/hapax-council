#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform float u_source;
uniform float u_shape;
uniform float u_thickness;
uniform float u_color_r;
uniform float u_color_g;
uniform float u_color_b;
uniform float u_color_a;
uniform float u_scale;
uniform float u_time;
uniform float u_width;
uniform float u_height;

#define PI 3.14159265359
#define TWO_PI 6.28318530718

// pseudo-audio data from noise (placeholder for real audio uniform)
float audioSample(float freq) {
    float t = u_time * 2.0;
    return 0.5 * sin(freq * 6.0 + t * 3.0)
         + 0.3 * sin(freq * 13.0 + t * 5.0)
         + 0.2 * sin(freq * 27.0 + t * 7.0);
}

float fftSample(float freq) {
    float t = u_time;
    float base = 0.3 + 0.2 * sin(t * 0.5);
    float v = base * exp(-freq * 2.0)
            + 0.4 * exp(-abs(freq - 0.3) * 8.0) * (0.5 + 0.5 * sin(t * 3.0))
            + 0.2 * exp(-abs(freq - 0.7) * 12.0) * (0.5 + 0.5 * sin(t * 1.7));
    return clamp(v, 0.0, 1.0);
}

void main() {
    vec2 uv = v_texcoord;
    vec4 color = vec4(u_color_r, u_color_g, u_color_b, u_color_a);
    float pxSize = u_thickness / min(u_width, u_height);
    float alpha = 0.0;

    if(u_shape < 0.5) {
        // linear visualization
        float x = uv.x;
        float value;
        if(u_source < 0.5) {
            value = audioSample(x) * u_scale;
        } else {
            value = fftSample(x) * u_scale;
        }
        float y = uv.y - 0.5;
        float dist;
        if(u_source < 0.5) {
            dist = abs(y - value * 0.4);
        } else {
            // bars from bottom
            dist = (0.5 - y) > value * 0.8 ? 1.0 : 0.0;
            dist = min(dist, abs((0.5 - y) - value * 0.8));
        }
        alpha = 1.0 - smoothstep(0.0, pxSize, dist);
    } else {
        // circular visualization
        vec2 center = uv - 0.5;
        float r = length(center);
        float angle = atan(center.y, center.x);
        float normAngle = (angle + PI) / TWO_PI;
        float value;
        if(u_source < 0.5) {
            value = audioSample(normAngle) * u_scale;
        } else {
            value = fftSample(normAngle) * u_scale;
        }
        float baseRadius = 0.25 * u_scale;
        float targetR = baseRadius + value * 0.15;
        float dist = abs(r - targetR);
        alpha = 1.0 - smoothstep(0.0, pxSize, dist);
        // add glow
        alpha += 0.3 * (1.0 - smoothstep(0.0, pxSize * 4.0, dist));
    }
    alpha = clamp(alpha, 0.0, 1.0);
    gl_FragColor = vec4(color.rgb, color.a * alpha);
}
