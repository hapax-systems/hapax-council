#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;
uniform float u_direction;
uniform float u_speed;
uniform float u_time;

// Authentic temporal slit-scan: each column (or row) of the output
// represents a different moment in time. The slit sweeps across the
// frame; pixels at the slit position are replaced with the current
// frame while all others retain their historical value from the
// temporal accumulator. Static objects render normally; moving objects
// distort proportional to their velocity relative to the scan direction.

void main() {
    vec2 uv = v_texcoord;

    // The scan slit position cycles across the frame
    float slit_pos = fract(u_time * u_speed * 0.02);
    float slit_width = u_speed * 0.02;

    if (u_direction < 0.5) {
        // Horizontal: slit is a vertical line sweeping left-to-right
        float dist = abs(uv.x - slit_pos);
        float wrap_dist = min(dist, 1.0 - dist);
        if (wrap_dist < slit_width) {
            // At the slit — sample current frame
            gl_FragColor = texture2D(tex, uv);
        } else {
            // Retain historical value from accumulator
            gl_FragColor = texture2D(tex_accum, uv);
        }
    } else {
        // Vertical: slit is a horizontal line sweeping top-to-bottom
        float dist = abs(uv.y - slit_pos);
        float wrap_dist = min(dist, 1.0 - dist);
        if (wrap_dist < slit_width) {
            gl_FragColor = texture2D(tex, uv);
        } else {
            gl_FragColor = texture2D(tex_accum, uv);
        }
    }
}
