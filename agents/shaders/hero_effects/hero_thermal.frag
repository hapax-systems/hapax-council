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

void main() {
    bool in_hero = v_texcoord.x >= u_hero_x && v_texcoord.x <= u_hero_x + u_hero_w
                && v_texcoord.y >= u_hero_y && v_texcoord.y <= u_hero_y + u_hero_h;
    if (!in_hero) {
        gl_FragColor = texture2D(tex, v_texcoord);
        return;
    }
    vec4 c = texture2D(tex, v_texcoord);
    float luma = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    // 5-stop false-color thermal palette
    vec3 thermal;
    if (luma < 0.2) {
        thermal = mix(vec3(0.0, 0.0, 0.1), vec3(0.1, 0.0, 0.5), luma / 0.2);
    } else if (luma < 0.4) {
        thermal = mix(vec3(0.1, 0.0, 0.5), vec3(0.8, 0.0, 0.2), (luma - 0.2) / 0.2);
    } else if (luma < 0.6) {
        thermal = mix(vec3(0.8, 0.0, 0.2), vec3(1.0, 0.5, 0.0), (luma - 0.4) / 0.2);
    } else if (luma < 0.8) {
        thermal = mix(vec3(1.0, 0.5, 0.0), vec3(1.0, 1.0, 0.0), (luma - 0.6) / 0.2);
    } else {
        thermal = mix(vec3(1.0, 1.0, 0.0), vec3(1.0, 1.0, 1.0), (luma - 0.8) / 0.2);
    }
    gl_FragColor = vec4(thermal, 1.0);
}
