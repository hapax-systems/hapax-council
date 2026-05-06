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
    // Kuwahara filter (oil painting) — 4-quadrant variance-based averaging
    int radius = 3;
    float fr = float(radius);
    vec3 mean[4];
    float var[4];
    mean[0] = vec3(0.0); mean[1] = vec3(0.0);
    mean[2] = vec3(0.0); mean[3] = vec3(0.0);
    var[0] = 0.0; var[1] = 0.0; var[2] = 0.0; var[3] = 0.0;
    vec2 px = vec2(1.0 / u_width, 1.0 / u_height);
    float count = (fr + 1.0) * (fr + 1.0);

    // Quadrant 0: top-left
    for (int j = 0; j <= 3; j++) {
        for (int i = 0; i <= 3; i++) {
            vec3 s = texture2D(tex, v_texcoord + vec2(float(-i), float(-j)) * px).rgb;
            mean[0] += s;
        }
    }
    mean[0] /= count;
    for (int j = 0; j <= 3; j++) {
        for (int i = 0; i <= 3; i++) {
            vec3 s = texture2D(tex, v_texcoord + vec2(float(-i), float(-j)) * px).rgb;
            vec3 d = s - mean[0];
            var[0] += dot(d, d);
        }
    }
    // Quadrant 1: top-right
    for (int j = 0; j <= 3; j++) {
        for (int i = 0; i <= 3; i++) {
            vec3 s = texture2D(tex, v_texcoord + vec2(float(i), float(-j)) * px).rgb;
            mean[1] += s;
        }
    }
    mean[1] /= count;
    for (int j = 0; j <= 3; j++) {
        for (int i = 0; i <= 3; i++) {
            vec3 s = texture2D(tex, v_texcoord + vec2(float(i), float(-j)) * px).rgb;
            vec3 d = s - mean[1];
            var[1] += dot(d, d);
        }
    }
    // Quadrant 2: bottom-left
    for (int j = 0; j <= 3; j++) {
        for (int i = 0; i <= 3; i++) {
            vec3 s = texture2D(tex, v_texcoord + vec2(float(-i), float(j)) * px).rgb;
            mean[2] += s;
        }
    }
    mean[2] /= count;
    for (int j = 0; j <= 3; j++) {
        for (int i = 0; i <= 3; i++) {
            vec3 s = texture2D(tex, v_texcoord + vec2(float(-i), float(j)) * px).rgb;
            vec3 d = s - mean[2];
            var[2] += dot(d, d);
        }
    }
    // Quadrant 3: bottom-right
    for (int j = 0; j <= 3; j++) {
        for (int i = 0; i <= 3; i++) {
            vec3 s = texture2D(tex, v_texcoord + vec2(float(i), float(j)) * px).rgb;
            mean[3] += s;
        }
    }
    mean[3] /= count;
    for (int j = 0; j <= 3; j++) {
        for (int i = 0; i <= 3; i++) {
            vec3 s = texture2D(tex, v_texcoord + vec2(float(i), float(j)) * px).rgb;
            vec3 d = s - mean[3];
            var[3] += dot(d, d);
        }
    }

    // Pick quadrant with lowest variance
    float minVar = var[0];
    vec3 result = mean[0];
    if (var[1] < minVar) { minVar = var[1]; result = mean[1]; }
    if (var[2] < minVar) { minVar = var[2]; result = mean[2]; }
    if (var[3] < minVar) { result = mean[3]; }

    gl_FragColor = vec4(result, 1.0);
}
