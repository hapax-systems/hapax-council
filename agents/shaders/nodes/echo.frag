#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;
uniform float u_frame_count;
uniform float u_decay_curve;
uniform float u_blend_mode;

void main() {
    vec4 cur = texture2D(tex, v_texcoord);
    vec4 acc = texture2D(tex_accum, v_texcoord);
    // weight for current frame in running average
    float w;
    if(u_decay_curve < 0.5) {
        // linear: equal weight
        w = 1.0 / u_frame_count;
    } else if(u_decay_curve < 1.5) {
        // exponential: heavier on recent
        w = 2.0 / (u_frame_count + 1.0);
    } else {
        // equal: simple average
        w = 1.0 / u_frame_count;
    }
    vec3 result;
    if(u_blend_mode < 0.5) {
        // average: weighted running mean
        result = mix(acc.rgb, cur.rgb, w);
    } else if(u_blend_mode < 1.5) {
        // additive
        result = acc.rgb * (1.0 - w) + cur.rgb;
    } else {
        // max
        result = max(acc.rgb * (1.0 - w * 0.5), cur.rgb);
    }
    gl_FragColor = vec4(clamp(result, 0.0, 1.0), 1.0);
}
