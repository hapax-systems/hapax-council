#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_prev;
uniform float u_threshold;
uniform float u_color_mode;

void main() {
    vec4 cur = texture2D(tex, v_texcoord);
    vec4 prev = texture2D(tex_prev, v_texcoord);
    vec3 d = abs(cur.rgb - prev.rgb);
    float mag = dot(d, vec3(0.299, 0.587, 0.114));
    float mask = step(u_threshold, mag);
    vec3 result;
    if(u_color_mode < 0.5) {
        // grayscale difference magnitude
        result = vec3(mag) * mask;
    } else if(u_color_mode < 1.5) {
        // binary white/black
        result = vec3(mask);
    } else {
        // original color where motion detected
        result = cur.rgb * mask;
    }
    gl_FragColor = vec4(result, 1.0);
}
