#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;
uniform float u_slice_count;     // number of horizontal slices (0=disabled)
uniform float u_slice_amplitude; // max px displacement per slice
uniform float u_pan_x;           // global pan amplitude (normalized)
uniform float u_pan_y;
uniform float u_rotation;        // radians amplitude
uniform float u_zoom;            // base zoom (1.0 = no zoom)
uniform float u_zoom_breath;     // zoom oscillation amplitude
uniform float u_width;
uniform float u_height;

void main() {
    vec2 uv = v_texcoord;

    // Global transform
    float t = u_time;
    float panX = sin(t) * u_pan_x / u_width;
    float panY = sin(t * 0.7) * u_pan_y / u_height;
    float rot = sin(t * 0.5) * u_rotation;
    float zoom = u_zoom + sin(t * 0.2) * u_zoom_breath;

    // Center, rotate, scale, translate
    uv -= 0.5;
    float c = cos(rot);
    float s = sin(rot);
    uv = mat2(c, -s, s, c) * uv;
    uv /= zoom;
    uv += 0.5;
    uv += vec2(panX, panY);

    // Per-slice horizontal displacement
    if (u_slice_count > 0.0) {
        float sliceIdx = floor(v_texcoord.y * u_slice_count);
        float slicePhase = t + sliceIdx * 0.15;
        float sliceShift = sin(slicePhase) * u_slice_amplitude / u_width;
        sliceShift += sin(slicePhase * 2.3) * (u_slice_amplitude * 0.5) / u_width;
        uv.x += sliceShift;
    }

    gl_FragColor = texture2D(tex, uv);
}
