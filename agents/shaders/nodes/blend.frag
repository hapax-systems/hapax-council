#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_b;
uniform float u_alpha;
uniform float u_mode;
void main() {
    vec4 a = texture2D(tex, v_texcoord);
    vec4 b = texture2D(tex_b, v_texcoord);
    vec3 r;
    if(u_mode<0.5) r=1.0-(1.0-a.rgb)*(1.0-b.rgb);
    else if(u_mode<1.5) r=a.rgb+b.rgb;
    else if(u_mode<2.5) r=a.rgb*b.rgb;
    else if(u_mode<3.5) r=abs(a.rgb-b.rgb);
    else r=mix(2.0*a.rgb*b.rgb, 1.0-2.0*(1.0-a.rgb)*(1.0-b.rgb), step(0.5,a.rgb));
    gl_FragColor = vec4(mix(a.rgb, r, u_alpha), 1.0);
}
