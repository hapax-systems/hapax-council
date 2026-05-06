#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_hero_x;
uniform float u_hero_y;
uniform float u_hero_w;
uniform float u_hero_h;
uniform float u_width;
uniform float u_height;

void main() {
    bool in_hero = v_texcoord.x >= u_hero_x && v_texcoord.x <= u_hero_x + u_hero_w
                && v_texcoord.y >= u_hero_y && v_texcoord.y <= u_hero_y + u_hero_h;
    if (!in_hero) {
        gl_FragColor = texture2D(tex, v_texcoord);
        return;
    }
    vec2 px = vec2(1.0 / u_width, 1.0 / u_height);
    float tl = dot(texture2D(tex, v_texcoord + vec2(-px.x, -px.y)).rgb, vec3(0.299, 0.587, 0.114));
    float t  = dot(texture2D(tex, v_texcoord + vec2( 0.0, -px.y)).rgb, vec3(0.299, 0.587, 0.114));
    float tr = dot(texture2D(tex, v_texcoord + vec2( px.x, -px.y)).rgb, vec3(0.299, 0.587, 0.114));
    float l  = dot(texture2D(tex, v_texcoord + vec2(-px.x,  0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float r  = dot(texture2D(tex, v_texcoord + vec2( px.x,  0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float bl = dot(texture2D(tex, v_texcoord + vec2(-px.x,  px.y)).rgb, vec3(0.299, 0.587, 0.114));
    float b  = dot(texture2D(tex, v_texcoord + vec2( 0.0,  px.y)).rgb, vec3(0.299, 0.587, 0.114));
    float br = dot(texture2D(tex, v_texcoord + vec2( px.x,  px.y)).rgb, vec3(0.299, 0.587, 0.114));
    float gx = -tl - 2.0*l - bl + tr + 2.0*r + br;
    float gy = -tl - 2.0*t - tr + bl + 2.0*b + br;
    float edge = sqrt(gx*gx + gy*gy);
    vec4 cur = texture2D(tex, v_texcoord);
    vec3 tint = cur.rgb * 0.15 + vec3(edge) * 0.85;
    gl_FragColor = vec4(tint, 1.0);
}
