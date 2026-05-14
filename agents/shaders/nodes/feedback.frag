#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;
uniform float u_decay;
uniform float u_zoom;
uniform float u_rotate;
uniform float u_blend_mode;
uniform float u_hue_shift;
uniform float u_trace_center_x;
uniform float u_trace_center_y;
uniform float u_trace_radius;
uniform float u_trace_strength;
void main() {
    vec2 center = vec2(0.5);
    vec2 uv = v_texcoord - center;
    float cs = cos(u_rotate);
    float sn = sin(u_rotate);
    uv = mat2(cs, -sn, sn, cs) * uv;
    uv /= u_zoom;
    uv += center;
    // Attenuate accumulation near frame edges to prevent corner ghost
    // artifact from zoom/rotate pushing content beyond frame boundaries.
    float edge_fade = smoothstep(0.0, 0.025, uv.x)
                    * smoothstep(0.0, 0.025, uv.y)
                    * smoothstep(0.0, 0.025, 1.0 - uv.x)
                    * smoothstep(0.0, 0.025, 1.0 - uv.y);
    vec4 acc = texture2D(tex_accum, uv) * edge_fade;
    // Trace-aware decay: ghostly afterimage where content dwelt
    vec2 trace_center = vec2(u_trace_center_x, u_trace_center_y);
    float dist_to_trace = distance(v_texcoord, trace_center);
    float trace_factor = smoothstep(u_trace_radius, 0.0, dist_to_trace) * u_trace_strength;
    float effective_decay = mix(u_decay, min(u_decay * 0.3, 0.015), trace_factor);
    acc.rgb *= (1.0 - effective_decay);
    if (u_hue_shift > 0.0) {
        float a = u_hue_shift * 3.14159 / 180.0;
        float c = cos(a);
        float s = sin(a);
        mat3 hue = mat3(
            0.213 + 0.787*c - 0.213*s, 0.213 - 0.213*c + 0.143*s, 0.213 - 0.213*c - 0.787*s,
            0.715 - 0.715*c - 0.715*s, 0.715 + 0.285*c + 0.140*s, 0.715 - 0.715*c + 0.715*s,
            0.072 - 0.072*c + 0.928*s, 0.072 - 0.072*c - 0.283*s, 0.072 + 0.928*c + 0.072*s
        );
        acc.rgb = hue * acc.rgb;
    }
    vec4 cur = texture2D(tex, v_texcoord);
    vec3 r;
    if (u_blend_mode < 0.5) r = max(acc.rgb, cur.rgb);
    else if (u_blend_mode < 1.5) r = 1.0 - (1.0 - acc.rgb) * (1.0 - cur.rgb);
    else r = acc.rgb + cur.rgb;
    gl_FragColor = vec4(clamp(r, 0.0, 1.0), 1.0);
}
