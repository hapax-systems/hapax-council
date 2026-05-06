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
    // Scanline CRT simulation
    vec4 c = texture2D(tex, v_texcoord);
    float line = mod(v_texcoord.y * u_height, 4.0);
    float scanline = smoothstep(0.0, 1.5, line) * smoothstep(4.0, 2.5, line);
    // Slight RGB channel offset for CRT phosphor feel
    float off = 0.5 / u_width;
    float r = texture2D(tex, v_texcoord + vec2(-off, 0.0)).r;
    float g = c.g;
    float b = texture2D(tex, v_texcoord + vec2( off, 0.0)).b;
    vec3 result = vec3(r, g, b) * (0.6 + 0.4 * scanline);
    gl_FragColor = vec4(result, 1.0);
}
