#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_saturation;    // 0=gray, 1=normal, 2+=hyper
uniform float u_brightness;    // multiplier
uniform float u_contrast;      // multiplier
uniform float u_sepia;         // 0-1 mix
uniform float u_hue_rotate;    // degrees
uniform float u_displacement;  // 0-1 luma-driven UV warp strength

vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0/3.0, 2.0/3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0/3.0, 1.0/3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
    vec2 uv = v_texcoord;

    // Displacement: warp UV based on luminance gradient of surrounding
    // pixels.  At u_displacement=0 the shader behaves identically to the
    // pre-displacement version.  At u_displacement=1 the warp is a
    // subtle luma-driven ripple (max ~1% of frame width).
    if (u_displacement > 0.001) {
        float texel = 1.0 / 1280.0;  // approximate; works for 720-1920
        float lR = dot(texture2D(tex, uv + vec2(texel, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
        float lL = dot(texture2D(tex, uv - vec2(texel, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
        float lU = dot(texture2D(tex, uv + vec2(0.0, texel)).rgb, vec3(0.299, 0.587, 0.114));
        float lD = dot(texture2D(tex, uv - vec2(0.0, texel)).rgb, vec3(0.299, 0.587, 0.114));
        vec2 grad = vec2(lR - lL, lU - lD);
        uv += grad * u_displacement * 0.01;
    }

    vec4 color = texture2D(tex, uv);

    // Contrast
    color.rgb = (color.rgb - 0.5) * u_contrast + 0.5;
    // Brightness
    color.rgb *= u_brightness;

    // Sepia
    if (u_sepia > 0.0) {
        float gray = dot(color.rgb, vec3(0.299, 0.587, 0.114));
        vec3 sep = vec3(gray * 1.2, gray * 1.0, gray * 0.8);
        color.rgb = mix(color.rgb, sep, u_sepia);
    }

    // Hue rotation + saturation
    vec3 hsv = rgb2hsv(color.rgb);
    hsv.x = fract(hsv.x + u_hue_rotate / 360.0);
    hsv.y *= u_saturation;
    color.rgb = hsv2rgb(hsv);

    gl_FragColor = vec4(clamp(color.rgb, 0.0, 1.0), color.a);
}
