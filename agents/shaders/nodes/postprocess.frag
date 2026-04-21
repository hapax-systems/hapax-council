#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_vignette_strength;
uniform float u_sediment_strength;
uniform float u_master_opacity;
uniform float u_anonymize;  // 0=off, 1=full posterize+noise face obscuring

float hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 19.19);
    return fract((p3.x + p3.y) * p3.z);
}

void main() {
    vec4 c = texture2D(tex, v_texcoord);

    // Anonymize: light safety net -- preserves studio detail, softens faces
    if (u_anonymize > 0.5) {
        // Light posterize -- reduces smooth gradients (skin) without killing textures
        c.rgb = floor(c.rgb * 6.0 + 0.5) / 6.0;
        // Subtle noise
        float n = hash(v_texcoord * 200.0 + c.rg * 5.0);
        c.rgb += (n - 0.5) * 0.08;
    }

    // Vignette
    vec2 uv = v_texcoord * 2.0 - 1.0;
    float d = length(uv);
    float vig = smoothstep(0.8, 1.8, d) * u_vignette_strength;
    c.rgb *= 1.0 - vig;

    // Sediment strip
    float sed = smoothstep(0.95, 1.0, v_texcoord.y) * u_sediment_strength;
    c.rgb *= 1.0 - sed;

    gl_FragColor = c;
}
