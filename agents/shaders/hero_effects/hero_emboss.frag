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
    // Emboss convolution kernel
    float tl = dot(texture2D(tex, v_texcoord + vec2(-px.x, -px.y)).rgb, vec3(0.299, 0.587, 0.114));
    float br = dot(texture2D(tex, v_texcoord + vec2( px.x,  px.y)).rgb, vec3(0.299, 0.587, 0.114));
    float emboss = tl - br + 0.5;
    vec4 cur = texture2D(tex, v_texcoord);
    // Tint with original color at low opacity for warmth
    vec3 result = vec3(emboss) * 0.7 + cur.rgb * 0.3;
    gl_FragColor = vec4(clamp(result, 0.0, 1.0), 1.0);
}
