#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_threshold;
uniform float u_color_mode;
uniform float u_width;
uniform float u_height;

float luminance(vec3 c) {
    return dot(c, vec3(0.299, 0.587, 0.114));
}

void main() {
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);
    // Sobel 3x3
    float tl = luminance(texture2D(tex, v_texcoord + vec2(-texel.x,  texel.y)).rgb);
    float t  = luminance(texture2D(tex, v_texcoord + vec2( 0.0,      texel.y)).rgb);
    float tr = luminance(texture2D(tex, v_texcoord + vec2( texel.x,  texel.y)).rgb);
    float l  = luminance(texture2D(tex, v_texcoord + vec2(-texel.x,  0.0)).rgb);
    float r  = luminance(texture2D(tex, v_texcoord + vec2( texel.x,  0.0)).rgb);
    float bl = luminance(texture2D(tex, v_texcoord + vec2(-texel.x, -texel.y)).rgb);
    float b  = luminance(texture2D(tex, v_texcoord + vec2( 0.0,     -texel.y)).rgb);
    float br = luminance(texture2D(tex, v_texcoord + vec2( texel.x, -texel.y)).rgb);
    float gx = -tl - 2.0*l - bl + tr + 2.0*r + br;
    float gy = -tl - 2.0*t - tr + bl + 2.0*b + br;
    float edge = sqrt(gx*gx + gy*gy);
    edge = step(u_threshold, edge);
    if (u_color_mode > 0.5) {
        vec4 color = texture2D(tex, v_texcoord);
        gl_FragColor = vec4(color.rgb * edge, color.a);
    } else {
        gl_FragColor = vec4(vec3(edge), 1.0);
    }
}
