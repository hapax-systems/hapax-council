#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_b;
uniform float u_key_r;
uniform float u_key_g;
uniform float u_key_b;
uniform float u_tolerance;
uniform float u_softness;
uniform float u_spill_suppression;

void main() {
    vec4 a = texture2D(tex, v_texcoord);
    vec4 b = texture2D(tex_b, v_texcoord);
    vec3 keyColor = vec3(u_key_r, u_key_g, u_key_b);
    // distance from key color
    float dist = distance(b.rgb, keyColor);
    // soft matte
    float alpha = smoothstep(u_tolerance - u_softness, u_tolerance + u_softness, dist);
    // spill suppression: reduce key color channel in non-keyed areas
    vec3 despilled = b.rgb;
    if(u_spill_suppression > 0.01) {
        // find dominant key channel and suppress it
        float spill = dot(b.rgb, keyColor) / (dot(keyColor, keyColor) + 0.001);
        spill = max(spill - 0.5, 0.0) * 2.0;
        despilled = b.rgb - keyColor * spill * u_spill_suppression * (1.0 - alpha);
        despilled = clamp(despilled, 0.0, 1.0);
    }
    // composite despilled B over A
    gl_FragColor = vec4(mix(a.rgb, despilled, alpha), 1.0);
}
