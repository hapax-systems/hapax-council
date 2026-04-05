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

    // Anonymize: aggressive posterize + heavy noise to destroy facial features
    if (u_anonymize > 0.5) {
        // Posterize to 3 levels — extreme reduction, destroys skin gradients
        c.rgb = floor(c.rgb * 3.0 + 0.5) / 3.0;
        // Heavy per-pixel noise grain
        float n = hash(v_texcoord * 300.0 + c.rg * 7.0);
        c.rgb += (n - 0.5) * 0.2;
        // Resolution reduction — quantize UV to simulate low-res
        vec2 loRes = floor(v_texcoord * 240.0) / 240.0;
        vec4 loC = texture2D(tex, loRes);
        loC.rgb = floor(loC.rgb * 3.0 + 0.5) / 3.0;
        c.rgb = mix(c.rgb, loC.rgb, 0.5);
        // Contrast crush
        c.rgb = mix(vec3(0.1), c.rgb, 0.8);
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
