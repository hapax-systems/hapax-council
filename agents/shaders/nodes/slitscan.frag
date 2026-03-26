#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;
uniform float u_direction;
uniform float u_speed;
uniform float u_buffer_frames;
uniform float u_time;
uniform float u_width;
uniform float u_height;

void main() {
    vec2 uv = v_texcoord;
    // compute scan position based on time
    float scan_pos = fract(u_time * u_speed / u_buffer_frames);
    float coord;
    if(u_direction < 0.5) {
        // vertical: each column from different time offset
        coord = uv.x;
    } else {
        // horizontal: each row from different time offset
        coord = uv.y;
    }
    // blend between current and accumulated based on column/row position
    float offset = abs(coord - scan_pos);
    offset = min(offset, 1.0 - offset); // wrap distance
    float mix_factor = smoothstep(0.0, 1.0/u_buffer_frames * 10.0, offset);
    vec4 cur = texture2D(tex, uv);
    vec4 acc = texture2D(tex_accum, uv);
    // near scan line: write current, far: keep accumulated
    gl_FragColor = mix(cur, acc, mix_factor);
}
