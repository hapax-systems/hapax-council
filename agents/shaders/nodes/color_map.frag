#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_blend;

vec3 irPalette(float t) {
    // blue -> purple -> red -> orange -> yellow -> white
    vec3 c;
    if (t < 0.2) {
        c = mix(vec3(0.0, 0.0, 0.5), vec3(0.5, 0.0, 0.5), t / 0.2);
    } else if (t < 0.4) {
        c = mix(vec3(0.5, 0.0, 0.5), vec3(1.0, 0.0, 0.0), (t - 0.2) / 0.2);
    } else if (t < 0.6) {
        c = mix(vec3(1.0, 0.0, 0.0), vec3(1.0, 0.5, 0.0), (t - 0.4) / 0.2);
    } else if (t < 0.8) {
        c = mix(vec3(1.0, 0.5, 0.0), vec3(1.0, 1.0, 0.0), (t - 0.6) / 0.2);
    } else {
        c = mix(vec3(1.0, 1.0, 0.0), vec3(1.0, 1.0, 1.0), (t - 0.8) / 0.2);
    }
    return c;
}

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    vec3 mapped = irPalette(lum);
    gl_FragColor = vec4(mix(color.rgb, mapped, u_blend), color.a);
}
