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
    // Halftone dot pattern
    float dot_size = 6.0;
    vec2 pixel = v_texcoord * vec2(u_width, u_height);
    vec2 cell = floor(pixel / dot_size) * dot_size + dot_size * 0.5;
    vec2 cell_uv = cell / vec2(u_width, u_height);
    vec4 c = texture2D(tex, cell_uv);
    float luma = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    float dist = distance(pixel, cell) / (dot_size * 0.5);
    float radius = luma * 1.2;
    float dot = smoothstep(radius + 0.1, radius - 0.1, dist);
    // Tint with the cell's color
    vec3 result = c.rgb * dot;
    gl_FragColor = vec4(result, 1.0);
}
