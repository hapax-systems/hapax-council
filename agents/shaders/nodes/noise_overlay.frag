#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_intensity;
uniform float u_animated;
uniform float u_time;
uniform float u_width;
uniform float u_height;
float hash(vec2 p){vec3 p3=fract(vec3(p.xyx)*0.1031);p3+=dot(p3,p3.yzx+33.33);return fract((p3.x+p3.y)*p3.z);}
void main() {
    vec4 c = texture2D(tex, v_texcoord);
    vec2 uv = floor(v_texcoord*vec2(u_width,u_height)/8.0);
    float n = hash(uv + (u_animated>0.5 ? floor(u_time*10.0) : 0.0));
    vec3 r = mix(2.0*c.rgb*vec3(n), 1.0-2.0*(1.0-c.rgb)*(1.0-vec3(n)), step(0.5,c.rgb));
    c.rgb = mix(c.rgb, r, u_intensity);
    gl_FragColor = c;
}
