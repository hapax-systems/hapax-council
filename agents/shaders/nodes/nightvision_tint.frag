#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_green_intensity;  // 0.7-1.0 typical
uniform float u_brightness;       // amplification factor
uniform float u_contrast;

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    // Convert to luminance (NVD photocathode response)
    float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    // Apply contrast
    lum = (lum - 0.5) * u_contrast + 0.5;
    // Amplify (image intensifier gain)
    lum *= u_brightness;
    lum = clamp(lum, 0.0, 1.0);
    // Green phosphor tint (P43 phosphor: peak 543nm)
    vec3 green = vec3(lum * 0.15, lum * u_green_intensity, lum * 0.1);
    gl_FragColor = vec4(green, 1.0);
}
