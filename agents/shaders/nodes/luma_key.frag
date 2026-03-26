#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_b;
uniform float u_threshold;
uniform float u_softness;
uniform float u_invert;
uniform float u_channel;

void main() {
    vec4 a = texture2D(tex, v_texcoord);
    vec4 b = texture2D(tex_b, v_texcoord);
    // extract key value from B
    float key;
    if(u_channel < 0.5) {
        key = dot(b.rgb, vec3(0.299, 0.587, 0.114)); // luminance
    } else if(u_channel < 1.5) {
        key = b.r;
    } else if(u_channel < 2.5) {
        key = b.g;
    } else {
        key = b.b;
    }
    // soft threshold
    float alpha = smoothstep(u_threshold - u_softness, u_threshold + u_softness, key);
    // invert if requested
    if(u_invert > 0.5) alpha = 1.0 - alpha;
    // composite B over A
    gl_FragColor = vec4(mix(a.rgb, b.rgb, alpha), 1.0);
}
