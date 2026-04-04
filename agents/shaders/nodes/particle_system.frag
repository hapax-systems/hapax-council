#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_emit_rate;
uniform float u_lifetime;
uniform float u_size;
uniform float u_color_r;
uniform float u_color_g;
uniform float u_color_b;
uniform float u_gravity_y;
uniform float u_time;
uniform float u_width;
uniform float u_height;

float hash(float n) { float p = fract(n * 0.1031); p *= p + 33.33; p *= p + p; return fract(p); }

void main() {
    vec4 base = texture2D(tex, v_texcoord);
    vec2 pixel = v_texcoord * vec2(u_width, u_height);
    float particle_count = min(u_emit_rate, 2000.0);
    float glow = 0.0;
    
    for (float i = 0.0; i < 200.0; i += 1.0) {
        if (i >= particle_count) break;
        
        float age = fract(u_time / u_lifetime + hash(i * 7.31));
        float spawn_x = hash(i * 13.7) * u_width;
        float spawn_y = hash(i * 23.1) * u_height;
        float vel_x = (hash(i * 37.3) - 0.5) * 100.0;
        float vel_y = (hash(i * 41.7) - 0.5) * 100.0;
        
        float px = spawn_x + vel_x * age;
        float py = spawn_y + vel_y * age + 0.5 * u_gravity_y * age * age;
        
        float dist = length(pixel - vec2(px, py));
        float fade = 1.0 - age;
        glow += fade * smoothstep(u_size, 0.0, dist);
    }
    
    vec3 particle_color = vec3(u_color_r, u_color_g, u_color_b) * min(glow, 3.0);
    gl_FragColor = vec4(base.rgb + particle_color, 1.0);
}
