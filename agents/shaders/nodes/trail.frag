#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;
uniform float u_fade;
uniform float u_opacity;
uniform float u_blend_mode;
uniform float u_drift_x;
uniform float u_drift_y;
uniform float u_time;
uniform float u_width;
uniform float u_height;
void main() {
    float t = u_time*0.015;
    float dx = u_drift_x*sin(t)*0.15/u_width;
    float dy = u_drift_y*cos(t*0.7)*0.15/u_height;
    vec2 shifted = v_texcoord+vec2(dx,dy);
    // Attenuate accumulation near frame edges to prevent corner ghost
    // artifact from drifting temporal echoes.  The smoothstep window
    // (~2.5 % of frame) is wide enough to suppress visible residue but
    // narrow enough to leave the interior trail aesthetic untouched.
    float edge_fade = smoothstep(0.0, 0.025, shifted.x)
                    * smoothstep(0.0, 0.025, shifted.y)
                    * smoothstep(0.0, 0.025, 1.0 - shifted.x)
                    * smoothstep(0.0, 0.025, 1.0 - shifted.y);
    vec4 acc = texture2D(tex_accum, shifted) * edge_fade;
    acc.rgb *= (1.0-u_fade);
    vec4 cur = texture2D(tex, v_texcoord);
    vec3 r;
    if(u_blend_mode<0.5) r=acc.rgb+cur.rgb*u_opacity;
    else if(u_blend_mode<1.5) r=1.0-(1.0-acc.rgb)*(1.0-cur.rgb*u_opacity);
    else if(u_blend_mode<2.5) r=acc.rgb*cur.rgb*u_opacity;
    else if(u_blend_mode<3.5) r=abs(acc.rgb-cur.rgb*u_opacity);
    else r=mix(2.0*acc.rgb*cur.rgb*u_opacity, 1.0-2.0*(1.0-acc.rgb)*(1.0-cur.rgb*u_opacity), step(0.5,acc.rgb));
    gl_FragColor = vec4(clamp(r,0.0,1.0), 1.0);
}
