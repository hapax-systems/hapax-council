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
    vec4 color = texture2D(tex, v_texcoord);
    float pixel_y = v_texcoord.y * u_height;
    float line = step(u_spacing - u_thickness, mod(pixel_y, u_spacing));
    color.rgb *= 1.0 - line * u_opacity;
    gl_FragColor = color;
}
