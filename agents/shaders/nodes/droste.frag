#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_zoom_speed;
uniform float u_spiral;
uniform float u_center_x;
uniform float u_center_y;
uniform float u_branches;
uniform float u_time;

#define PI 3.14159265359
#define TWO_PI 6.28318530718

void main() {
    vec2 center = vec2(u_center_x, u_center_y);
    vec2 uv = v_texcoord - center;
    // convert to polar
    float r = length(uv);
    float angle = atan(uv.y, uv.x);
    // avoid log(0)
    r = max(r, 0.001);
    // log-polar transform (Droste effect)
    float logr = log(r);
    float n = floor(u_branches);
    // apply spiral rotation
    float a = angle + u_spiral * logr;
    // apply zoom animation
    logr += u_time * u_zoom_speed * 0.1;
    // wrap the log radius to create recursion
    float scale = TWO_PI / log(2.0);
    logr = mod(logr * scale / n, TWO_PI) * n / scale;
    // wrap angle for branches
    a = mod(a, TWO_PI / n) * n / TWO_PI;
    a = a * TWO_PI;
    // back to cartesian
    float new_r = exp(logr);
    vec2 newUV = vec2(cos(a), sin(a)) * new_r;
    newUV += center;
    // tile the texture coordinates
    newUV = fract(newUV);
    gl_FragColor = texture2D(tex, newUV);
}
