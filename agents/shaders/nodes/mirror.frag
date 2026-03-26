#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_axis;
uniform float u_position;

void main() {
    vec2 uv = v_texcoord;
    // axis: 0=vertical, 1=horizontal, 2=both
    if (u_axis < 0.5 || u_axis > 1.5) {
        // vertical mirror
        if (uv.x > u_position) {
            uv.x = 2.0 * u_position - uv.x;
        }
    }
    if (u_axis > 0.5) {
        // horizontal mirror
        if (uv.y > u_position) {
            uv.y = 2.0 * u_position - uv.y;
        }
    }
    gl_FragColor = texture2D(tex, uv);
}
