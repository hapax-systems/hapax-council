#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_displacement;
uniform float u_line_density;
uniform float u_line_width;
uniform float u_color_mode;
uniform float u_height;

void main() {
    vec2 uv = v_texcoord;
    vec4 color = texture2D(tex, uv);
    float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    // scan line position
    float linePos = mod(uv.y * u_height, u_line_density);
    float line = step(u_line_density - u_line_width, linePos);
    // displace vertically by luminance
    float displaced_y = uv.y + lum * u_displacement * 0.01;
    vec4 dispColor = texture2D(tex, vec2(uv.x, clamp(displaced_y, 0.0, 1.0)));
    float dispLum = dot(dispColor.rgb, vec3(0.299, 0.587, 0.114));
    vec3 result;
    if (u_color_mode > 0.5) {
        result = dispColor.rgb * line;
    } else {
        result = vec3(dispLum * line);
    }
    gl_FragColor = vec4(result, 1.0);
}
