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
    vec2 pixel = vec2(max(u_width, 1.0), max(u_height, 1.0));
    float block_px = 14.0;
    vec2 block_uv = block_px / pixel;
    vec2 coarse_uv = (floor(v_texcoord / block_uv) + 0.5) * block_uv;
    coarse_uv = clamp(coarse_uv, vec2(0.0), vec2(1.0));

    float luma = 0.0;
    float weight_total = 0.0;
    for (float y = -1.0; y <= 1.0; y += 1.0) {
        for (float x = -1.0; x <= 1.0; x += 1.0) {
            vec2 sample_uv = clamp(coarse_uv + vec2(x, y) * block_uv, vec2(0.0), vec2(1.0));
            vec4 c = texture2D(tex, sample_uv);
            float weight = 1.0;
            if (x == 0.0 && y == 0.0) {
                weight = 2.0;
            }
            luma += dot(c.rgb, vec3(0.299, 0.587, 0.114)) * weight;
            weight_total += weight;
        }
    }
    luma = floor((luma / weight_total) * 8.0) / 8.0;
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
    gl_FragColor = vec4(thermal * 0.92, 1.0);
}
