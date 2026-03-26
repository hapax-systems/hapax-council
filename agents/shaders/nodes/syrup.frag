#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_color_r;
uniform float u_color_g;
uniform float u_color_b;
uniform float u_top_alpha;
uniform float u_bottom_alpha;

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    float alpha = mix(u_bottom_alpha, u_top_alpha, v_texcoord.y);
    vec3 overlay = vec3(u_color_r, u_color_g, u_color_b);
    gl_FragColor = vec4(mix(color.rgb, overlay, alpha), color.a);
}
