#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_opacity;
uniform float u_spacing;
uniform float u_thickness;
uniform float u_height;
void main() {
    vec4 c = texture2D(tex, v_texcoord);
    float line = step(u_spacing - u_thickness, mod(v_texcoord.y * u_height, u_spacing));
    c.rgb *= 1.0 - line * u_opacity;
    gl_FragColor = c;
}
