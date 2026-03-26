#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_threshold;
uniform float u_radius;
uniform float u_alpha;
uniform float u_width;
uniform float u_height;
void main() {
    vec4 c = texture2D(tex, v_texcoord);
    vec2 tx = vec2(1.0/u_width, 1.0/u_height) * u_radius * 0.25;
    vec3 g = vec3(0.0); float t = 0.0;
    for (float x=-2.0; x<=2.0; x+=1.0) for (float y=-2.0; y<=2.0; y+=1.0) {
        vec4 s = texture2D(tex, v_texcoord + vec2(x,y)*tx);
        float l = dot(s.rgb, vec3(0.299,0.587,0.114));
        float b = smoothstep(u_threshold-0.1, u_threshold+0.1, l);
        float w = exp(-(x*x+y*y)/4.0);
        g += s.rgb*b*w; t += w;
    }
    c.rgb += (g/t)*u_alpha;
    gl_FragColor = vec4(clamp(c.rgb,0.0,1.0), c.a);
}
