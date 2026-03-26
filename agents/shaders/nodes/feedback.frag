#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;
uniform float u_decay;
uniform float u_zoom;
uniform float u_rotate;
uniform float u_blend_mode;
uniform float u_hue_shift;
uniform float u_time;

#define PI 3.14159265359

vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0/3.0, 2.0/3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0*d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0/3.0, 1.0/3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
    vec2 center = vec2(0.5);
    vec2 uv = v_texcoord - center;
    // zoom
    uv /= u_zoom;
    // rotate
    float ca = cos(u_rotate);
    float sa = sin(u_rotate);
    uv = vec2(uv.x*ca - uv.y*sa, uv.x*sa + uv.y*ca);
    uv += center;
    // sample accumulated with zoom/rotate
    vec4 acc = texture2D(tex_accum, uv);
    // apply decay
    acc.rgb *= (1.0 - u_decay);
    // apply hue shift to accumulated
    if(u_hue_shift > 0.01) {
        vec3 hsv = rgb2hsv(acc.rgb);
        hsv.x = fract(hsv.x + u_hue_shift / 360.0);
        acc.rgb = hsv2rgb(hsv);
    }
    // current frame
    vec4 cur = texture2D(tex, v_texcoord);
    // blend
    vec3 r;
    if(u_blend_mode < 0.5) r = max(acc.rgb, cur.rgb); // lighter
    else if(u_blend_mode < 1.5) r = 1.0 - (1.0-acc.rgb)*(1.0-cur.rgb); // screen
    else if(u_blend_mode < 2.5) r = acc.rgb + cur.rgb; // additive
    else r = abs(acc.rgb - cur.rgb); // difference
    gl_FragColor = vec4(clamp(r, 0.0, 1.0), 1.0);
}
