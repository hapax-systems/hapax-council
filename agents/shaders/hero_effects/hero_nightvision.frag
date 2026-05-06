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
    // Night vision: green-channel amplification + noise grain
    vec4 c = texture2D(tex, v_texcoord);
    float luma = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    // Amplify
    luma = pow(luma, 0.6) * 1.4;
    // Simple hash noise
    float noise = fract(sin(dot(v_texcoord * vec2(u_width, u_height), vec2(12.9898, 78.233))) * 43758.5453);
    luma += (noise - 0.5) * 0.08;
    vec3 nv = vec3(luma * 0.2, luma * 0.9, luma * 0.15);
    gl_FragColor = vec4(clamp(nv, 0.0, 1.0), 1.0);
}
