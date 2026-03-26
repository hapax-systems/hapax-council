#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_amount;
uniform float u_radius;
uniform float u_width;
uniform float u_height;

void main() {
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height) * u_radius;
    vec4 color = texture2D(tex, v_texcoord);
    vec4 blur = texture2D(tex, v_texcoord + vec2(-texel.x, -texel.y))
              + texture2D(tex, v_texcoord + vec2( texel.x, -texel.y))
              + texture2D(tex, v_texcoord + vec2(-texel.x,  texel.y))
              + texture2D(tex, v_texcoord + vec2( texel.x,  texel.y));
    blur *= 0.25;
    gl_FragColor = vec4(color.rgb + (color.rgb - blur.rgb) * u_amount, color.a);
}
