#version 100
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_time;

// Ambient parameters driven by visual layer state
uniform float u_ambient_speed;      // 0.0-1.0, default 0.08
uniform float u_ambient_turbulence; // 0.0-1.0, default 0.1
uniform float u_ambient_warmth;     // 0.0=cool teal, 1.0=warm red
uniform float u_ambient_brightness; // 0.0-1.0, default 0.25

// -- Noise functions (Perlin-style) --

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);

    return mix(
        mix(hash(i + vec2(0.0, 0.0)), hash(i + vec2(1.0, 0.0)), u.x),
        mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
        u.y
    );
}

// Fractal Brownian Motion — multiple octaves of noise
float fbm(vec2 p) {
    float turb = max(u_ambient_turbulence, 0.05);
    int octaves = int(2.0 + turb * 4.0); // 2-6 octaves based on turbulence
    float value = 0.0;
    float amplitude = 0.5;
    float frequency = 1.0;

    for (int i = 0; i < 6; i++) {
        if (i >= octaves) break;
        value += amplitude * noise(p * frequency);
        frequency *= 2.0;
        amplitude *= 0.5;
    }
    return value;
}

void main() {
    vec2 uv = v_texcoord;

    // Original camera image
    vec4 cam = texture2D(tex, uv);

    // Time-varying offset for animation
    float speed = max(u_ambient_speed, 0.01);
    float t = u_time * speed * 0.3;

    // Flow field: offset uv by noise gradient for organic movement
    vec2 flow_uv = uv * 3.0 + vec2(t * 0.7, t * 0.5);
    float flow = fbm(flow_uv);
    float flow2 = fbm(flow_uv + vec2(5.2, 1.3) + t * 0.2);

    // Color: mix between cool teal and warm red based on warmth uniform
    vec3 cool = vec3(0.05, 0.15, 0.18);   // deep teal (#0D2730)
    vec3 warm = vec3(0.25, 0.08, 0.05);   // muted red (#401410)
    vec3 base_color = mix(cool, warm, u_ambient_warmth);

    // Apply noise as luminance variation
    float lum = flow * 0.6 + flow2 * 0.4;
    lum = lum * u_ambient_brightness;

    vec3 ambient = base_color + vec3(lum * 0.3, lum * 0.25, lum * 0.35);

    // Blend: ambient layer sits BEHIND the camera image
    // When camera is active, the ambient is very subtle (barely visible)
    // The visual layer zones render on TOP via Cairo overlay
    float blend = 0.15; // subtle ambient undertone
    vec3 result = mix(cam.rgb, ambient, blend);

    gl_FragColor = vec4(result, 1.0);
}
