#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform float u_type;
uniform float u_frequency_x;
uniform float u_frequency_y;
uniform float u_octaves;
uniform float u_amplitude;
uniform float u_speed;
uniform float u_seed;
uniform float u_time;

// hash functions
vec3 mod289(vec3 x) { return x - floor(x * (1.0/289.0)) * 289.0; }
vec2 mod289v2(vec2 x) { return x - floor(x * (1.0/289.0)) * 289.0; }
vec3 permute(vec3 x) { return mod289(((x*34.0)+1.0)*x); }

// simplex 2D noise
float snoise(vec2 v) {
    const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                        -0.577350269189626, 0.024390243902439);
    vec2 i = floor(v + dot(v, C.yy));
    vec2 x0 = v - i + dot(i, C.xx);
    vec2 i1;
    i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
    vec4 x12 = x0.xyxy + C.xxzz;
    x12.xy -= i1;
    i = mod289v2(i);
    vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0))
                     + i.x + vec3(0.0, i1.x, 1.0));
    vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy),
                            dot(x12.zw,x12.zw)), 0.0);
    m = m*m;
    m = m*m;
    vec3 x = 2.0 * fract(p * C.www) - 1.0;
    vec3 h = abs(x) - 0.5;
    vec3 ox = floor(x + 0.5);
    vec3 a0 = x - ox;
    m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);
    vec3 g;
    g.x = a0.x * x0.x + h.x * x0.y;
    g.yz = a0.yz * x12.xz + h.yz * x12.yw;
    return 130.0 * dot(m, g);
}

// value noise for perlin-like
float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1+u_seed, 311.7+u_seed))) * 43758.5453);
}

float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f*f*(3.0-2.0*f);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

// worley / cellular
float worley(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float minDist = 1.0;
    for(int y = -1; y <= 1; y++) {
        for(int x = -1; x <= 1; x++) {
            vec2 neighbor = vec2(float(x), float(y));
            vec2 point = vec2(hash(i + neighbor + u_seed),
                             hash(i + neighbor + u_seed + 37.0));
            vec2 diff = neighbor + point - f;
            minDist = min(minDist, length(diff));
        }
    }
    return minDist;
}

void main() {
    vec2 uv = v_texcoord * vec2(u_frequency_x, u_frequency_y);
    float t = u_time * u_speed;
    float value = 0.0;
    float amp = 1.0;
    float freq = 1.0;
    float maxAmp = 0.0;
    int oct = int(u_octaves);
    for(int i = 0; i < 8; i++) {
        if(i >= oct) break;
        vec2 p = uv * freq + t * 0.5;
        float n;
        if(u_type < 0.5) {
            n = vnoise(p); // perlin-like
        } else if(u_type < 1.5) {
            n = snoise(p) * 0.5 + 0.5; // simplex
        } else {
            n = 1.0 - worley(p); // worley
        }
        value += n * amp;
        maxAmp += amp;
        amp *= 0.5;
        freq *= 2.0;
    }
    value /= maxAmp;
    value *= u_amplitude;
    gl_FragColor = vec4(vec3(value), 1.0);
}
