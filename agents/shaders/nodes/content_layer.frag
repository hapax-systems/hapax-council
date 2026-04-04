#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D content_slot_0;
uniform sampler2D content_slot_1;
uniform sampler2D content_slot_2;
uniform sampler2D content_slot_3;
uniform float u_salience;
uniform float u_intensity;
uniform float u_material;
uniform float u_time;

float hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 19.19);
    return fract((p3.x + p3.y) * p3.z);
}

void main() {
    vec2 uv = v_texcoord;

    // When no content is recruited (salience=0), pass through unchanged
    if (u_salience < 0.01) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    vec3 base = texture2D(tex, uv).rgb;

    // Blend recruited content from slot 0
    vec4 c0 = texture2D(content_slot_0, uv);
    float noise = hash(v_texcoord * 30.0 + u_time * 0.05);
    float mat_factor = smoothstep(1.0 - u_salience, 1.0 - u_salience + 0.3, noise);
    vec3 weighted = c0.rgb * mat_factor * u_salience;

    // Screen blend for content compositing
    base = 1.0 - (1.0 - base) * (1.0 - weighted);

    gl_FragColor = vec4(base, 1.0);
}
