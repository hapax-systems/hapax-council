// Screwm QuakeC — live cognitive coupling
// Reads /dev/shm state files to drive tower behavior

float coupling_next_poll;
float coupling_poll_interval;
float coupling_energy;
float coupling_voice_active;
float coupling_reverie_salience;
float coupling_reverie_trace;
float coupling_reverie_temporal;
float coupling_reverie_spectral;
float coupling_reverie_material;
float coupling_reverie_inversion;
float coupling_reverie_aperture;
float coupling_reverie_thermal;
float coupling_audio_rms;
float coupling_audio_onset;
float coupling_effect_review_preset;
float coupling_effect_drift_active_ratio;
float coupling_effect_drift_active_slot_ratio;
float coupling_effect_drift_active_effect_ratio;
float coupling_effect_drift_fast_ratio;
float coupling_effect_drift_slow_ratio;
float coupling_effect_drift_kind_variance;
float coupling_effect_drift_max_delta;
float coupling_effect_drift_density;
float coupling_effect_drift_density_currency;
float coupling_effect_drift_region_count;
float coupling_effect_drift_tonal;
float coupling_effect_drift_atmospheric;
float coupling_effect_drift_temporal;
float coupling_effect_drift_texture;
float coupling_effect_drift_edge;
float coupling_effect_drift_compositing;
float coupling_effect_mode_tonal;
float coupling_effect_mode_atmospheric;
float coupling_effect_mode_temporal;
float coupling_effect_mode_texture;
float coupling_effect_mode_edge;
float coupling_effect_mode_compositing;
float coupling_visual_chain_drift;
float coupling_visual_chain_color;
float coupling_visual_chain_feedback;
float coupling_visual_chain_aperture;
float coupling_visual_chain_param_pressure;
float coupling_local_mirror;
float coupling_local_kaleidoscope;
float coupling_local_warp;
float coupling_local_fisheye;
float coupling_local_transform;
float coupling_local_displacement;
float coupling_local_droste;
float coupling_local_tunnel;
float coupling_local_tile;
float coupling_local_drift;
float coupling_local_breathing;
float coupling_local_count;
float coupling_shader_plan_color;
float coupling_shader_plan_motion;
float coupling_shader_plan_feedback;
float coupling_shader_plan_post;
float coupling_shader_plan_temporal_ratio;
string coupling_current_mode;
float coupling_mode_check_next;

void() coupling_init =
{
    CAMERA_PERIOD = 0;
    CAMERA_ORBIT_PERIOD = 360.0;
    CAMERA_ORBIT_RADIUS = 220.0;
    CAMERA_ORBIT_TWO_PI = 6.283185;
    coupling_poll_interval = 1.0;
    coupling_energy = 0.5;
    coupling_voice_active = 0;
    coupling_reverie_salience = 0;
    coupling_reverie_trace = 0;
    coupling_reverie_temporal = 0;
    coupling_reverie_spectral = 0;
    coupling_reverie_material = 0;
    coupling_reverie_inversion = 0;
    coupling_reverie_aperture = 0;
    coupling_reverie_thermal = 0;
    coupling_audio_rms = 0;
    coupling_audio_onset = 0;
    coupling_effect_review_preset = 0;
    coupling_effect_drift_active_ratio = 0;
    coupling_effect_drift_active_slot_ratio = 0;
    coupling_effect_drift_active_effect_ratio = 0;
    coupling_effect_drift_fast_ratio = 0;
    coupling_effect_drift_slow_ratio = 0;
    coupling_effect_drift_kind_variance = 0;
    coupling_effect_drift_max_delta = 0;
    coupling_effect_drift_density = 0;
    coupling_effect_drift_density_currency = 0;
    coupling_effect_drift_region_count = 0;
    coupling_effect_drift_tonal = 0;
    coupling_effect_drift_atmospheric = 0;
    coupling_effect_drift_temporal = 0;
    coupling_effect_drift_texture = 0;
    coupling_effect_drift_edge = 0;
    coupling_effect_drift_compositing = 0;
    coupling_effect_mode_tonal = 0;
    coupling_effect_mode_atmospheric = 0;
    coupling_effect_mode_temporal = 0;
    coupling_effect_mode_texture = 0;
    coupling_effect_mode_edge = 0;
    coupling_effect_mode_compositing = 0;
    coupling_visual_chain_drift = 0;
    coupling_visual_chain_color = 0;
    coupling_visual_chain_feedback = 0;
    coupling_visual_chain_aperture = 0;
    coupling_visual_chain_param_pressure = 0;
    coupling_local_mirror = 0;
    coupling_local_kaleidoscope = 0;
    coupling_local_warp = 0;
    coupling_local_fisheye = 0;
    coupling_local_transform = 0;
    coupling_local_displacement = 0;
    coupling_local_droste = 0;
    coupling_local_tunnel = 0;
    coupling_local_tile = 0;
    coupling_local_drift = 0;
    coupling_local_breathing = 0;
    coupling_local_count = 0;
    coupling_shader_plan_color = 0;
    coupling_shader_plan_motion = 0;
    coupling_shader_plan_feedback = 0;
    coupling_shader_plan_post = 0;
    coupling_shader_plan_temporal_ratio = 0;
    coupling_next_poll = time + 0.5;
    coupling_current_mode = "rnd";
    coupling_mode_check_next = time + 5.0;
};

float(string path, float fallback) coupling_read_float =
{
    float fh;
    string line;
    float val;

    fh = fopen(path, FILE_READ);
    if (fh < 0)
        return fallback;
    line = fgets(fh);
    fclose(fh);
    if (!line)
        return fallback;

    val = stof(line);
    if (val < 0)
        return 0;
    if (val > 1)
        return 1;
    return val;
};

float() coupling_read_effect_review_preset =
{
    float fh;
    string line;
    float val;

    fh = fopen("data/effect-review-preset.txt", FILE_READ);
    if (fh < 0)
        return 0;
    line = fgets(fh);
    fclose(fh);
    if (!line)
        return 0;

    val = stof(line);
    if (val < 0)
        return 0;
    if (val > 7)
        return 7;
    return val;
};

void(float u1x, float u1y, float u1z, float u1w, float u2x, float u2y, float u2z, float u2w, float u3x, float u3y, float u3z, float u3w, float u4x, float u4y, float u4z, float u4w) coupling_write_uservecs =
{
    string vec;

    vec = ftos(u1x);
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u1y));
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u1z));
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u1w));
    cvar_set("r_glsl_postprocess_uservec1", vec);

    vec = ftos(u2x);
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u2y));
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u2z));
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u2w));
    cvar_set("r_glsl_postprocess_uservec2", vec);

    vec = ftos(u3x);
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u3y));
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u3z));
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u3w));
    cvar_set("r_glsl_postprocess_uservec3", vec);

    vec = ftos(u4x);
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u4y));
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u4z));
    vec = strcat(vec, " ");
    vec = strcat(vec, ftos(u4w));
    cvar_set("r_glsl_postprocess_uservec4", vec);
};

float(float value, float floor_value, float ceil_value) coupling_clamp_range =
{
    if (value < floor_value)
        return floor_value;
    if (value > ceil_value)
        return ceil_value;
    return value;
};

float(float a, float b) coupling_max2 =
{
    if (a > b)
        return a;
    return b;
};

float() coupling_apply_effect_review_preset =
{
    float p;
    p = coupling_effect_review_preset;

    if (p < 0.5)
        return 0;

    if (p < 1.5)
    {
        // 1: reference/readability baseline - drift visible, media readable.
        coupling_write_uservecs(0.07, 1.75, 0.00, 0.035, 0.42, 1.45, 0, 0.12, 0.018, 0.085, 0, 0, 0, 0, 0, 0);
        return 1;
    }
    if (p < 2.5)
    {
        // 2: prism aura - strongest chroma/edge drift without blackout.
        coupling_write_uservecs(0.04, 3.55, 0.02, 0.026, 1.10, 2.35, 0, 0.20, 0.045, 0.140, 0, 0, 0.02, 0, 0, 0);
        return 1;
    }
    if (p < 3.5)
    {
        // 3: feedback/smear - motion/noise/block drift stress.
        coupling_write_uservecs(0.06, 2.20, 0.00, 0.060, 0.72, 1.55, 0, 0.08, 0.095, 0.190, 0, 0, 0, 0, 0, 0);
        return 1;
    }
    if (p < 4.5)
    {
        // 4: halftone/posterize - image processing pressure, still legible.
        coupling_write_uservecs(0.03, 1.90, 0.04, 0.025, 0.70, 1.55, 7, 0.16, 0.020, 0.085, 6, 0, 0, 0, 0, 0);
        return 1;
    }
    if (p < 5.5)
    {
        // 5: emboss/aperture/thermal - material and attention pressure.
        coupling_write_uservecs(0.07, 1.80, 0.08, 0.035, 0.62, 1.80, 0, 0.22, 0.018, 0.090, 0, 0, 0.42, 0.04, 0.10, 0.48);
        return 1;
    }

    if (p < 6.5)
    {
        // 6: threshold/inversion stress - proof bounds are controlled.
        coupling_write_uservecs(0.04, 1.55, 0.00, 0.022, 0.46, 1.25, 0, 0.08, 0.010, 0.075, 0, 0.18, 0, 0.18, 0.02, 0.10);
        return 1;
    }

    // 7: shader-load canary - deliberately unmistakable and not for normal use.
    coupling_write_uservecs(0.00, 0.00, 0.00, 0.000, 0.00, 0.00, 0, 0.00, 0, 0.000, 0, 0, 0, 1.00, 0, 0);
    return 1;
};

void() coupling_read_stimmung =
{
    float fh = fopen("data/stimmung-energy.txt", FILE_READ);
    if (fh < 0)
        return;
    string line = fgets(fh);
    fclose(fh);
    if (line)
    {
        float val = stof(line);
        if (val >= 0 && val <= 1)
            coupling_energy = val;
    }
};

void() coupling_read_voice =
{
    float fh = fopen("data/voice-active.txt", FILE_READ);
    if (fh < 0)
        return;
    string line = fgets(fh);
    fclose(fh);
    if (line)
    {
        float val = stof(line);
        coupling_voice_active = val;
    }
};

void() coupling_read_reverie =
{
    coupling_reverie_salience = coupling_read_float("data/reverie-salience.txt", 0);
    coupling_reverie_trace = coupling_read_float("data/reverie-trace.txt", 0);
    coupling_reverie_temporal = coupling_read_float("data/reverie-temporal.txt", 0);
    coupling_reverie_spectral = coupling_read_float("data/reverie-spectral.txt", 0);
    coupling_reverie_material = coupling_read_float("data/reverie-material.txt", 0);
    coupling_reverie_inversion = coupling_read_float("data/reverie-inversion.txt", 0);
    coupling_reverie_aperture = coupling_read_float("data/reverie-aperture.txt", 0);
    coupling_reverie_thermal = coupling_read_float("data/reverie-thermal.txt", 0);
};

void() coupling_read_audio =
{
    coupling_audio_rms = coupling_read_float("data/audio-rms.txt", 0);
    coupling_audio_onset = coupling_read_float("data/audio-onset.txt", 0);
};

void() coupling_read_effect_drift =
{
    coupling_effect_drift_active_ratio = coupling_read_float("data/effect-drift-active-ratio.txt", 0);
    coupling_effect_drift_active_slot_ratio = coupling_read_float("data/effect-drift-active-slot-ratio.txt", 0);
    coupling_effect_drift_active_effect_ratio = coupling_read_float("data/effect-drift-active-effect-ratio.txt", 0);
    coupling_effect_drift_fast_ratio = coupling_read_float("data/effect-drift-fast-ratio.txt", 0);
    coupling_effect_drift_slow_ratio = coupling_read_float("data/effect-drift-slow-ratio.txt", 0);
    coupling_effect_drift_kind_variance = coupling_read_float("data/effect-drift-kind-variance.txt", 0);
    coupling_effect_drift_max_delta = coupling_read_float("data/effect-drift-max-delta.txt", 0);
    coupling_effect_drift_density = coupling_read_float("data/effect-drift-density.txt", 0);
    coupling_effect_drift_density_currency = coupling_read_float("data/effect-drift-density-currency.txt", 0);
    coupling_effect_drift_region_count = coupling_read_float("data/effect-drift-region-count.txt", 0);
    coupling_effect_drift_tonal = coupling_read_float("data/effect-drift-tonal.txt", 0);
    coupling_effect_drift_atmospheric = coupling_read_float("data/effect-drift-atmospheric.txt", 0);
    coupling_effect_drift_temporal = coupling_read_float("data/effect-drift-temporal.txt", 0);
    coupling_effect_drift_texture = coupling_read_float("data/effect-drift-texture.txt", 0);
    coupling_effect_drift_edge = coupling_read_float("data/effect-drift-edge.txt", 0);
    coupling_effect_drift_compositing = coupling_read_float("data/effect-drift-compositing.txt", 0);
    coupling_effect_mode_tonal = coupling_read_float("data/effect-drift-mode-tonal.txt", 0);
    coupling_effect_mode_atmospheric = coupling_read_float("data/effect-drift-mode-atmospheric.txt", 0);
    coupling_effect_mode_temporal = coupling_read_float("data/effect-drift-mode-temporal.txt", 0);
    coupling_effect_mode_texture = coupling_read_float("data/effect-drift-mode-texture.txt", 0);
    coupling_effect_mode_edge = coupling_read_float("data/effect-drift-mode-edge.txt", 0);
    coupling_effect_mode_compositing = coupling_read_float("data/effect-drift-mode-compositing.txt", 0);
    coupling_visual_chain_drift = coupling_read_float("data/visual-chain-drift.txt", 0);
    coupling_visual_chain_color = coupling_read_float("data/visual-chain-color.txt", 0);
    coupling_visual_chain_feedback = coupling_read_float("data/visual-chain-feedback.txt", 0);
    coupling_visual_chain_aperture = coupling_read_float("data/visual-chain-aperture.txt", 0);
    coupling_visual_chain_param_pressure = coupling_read_float("data/visual-chain-param-pressure.txt", 0);
};

void() coupling_read_local_effects =
{
    coupling_local_mirror = coupling_read_float("data/local-effect-01.txt", 0);
    coupling_local_kaleidoscope = coupling_read_float("data/local-effect-02.txt", 0);
    coupling_local_warp = coupling_read_float("data/local-effect-03.txt", 0);
    coupling_local_fisheye = coupling_read_float("data/local-effect-04.txt", 0);
    coupling_local_transform = coupling_read_float("data/local-effect-05.txt", 0);
    coupling_local_displacement = coupling_read_float("data/local-effect-06.txt", 0);
    coupling_local_droste = coupling_read_float("data/local-effect-07.txt", 0);
    coupling_local_tunnel = coupling_read_float("data/local-effect-08.txt", 0);
    coupling_local_tile = coupling_read_float("data/local-effect-09.txt", 0);
    coupling_local_drift = coupling_read_float("data/local-effect-10.txt", 0);
    coupling_local_breathing = coupling_read_float("data/local-effect-11.txt", 0);
    coupling_local_count = coupling_read_float("data/local-effect-count.txt", 0);
    coupling_shader_plan_color = coupling_read_float("data/shader-plan-color.txt", 0);
    coupling_shader_plan_motion = coupling_read_float("data/shader-plan-motion.txt", 0);
    coupling_shader_plan_feedback = coupling_read_float("data/shader-plan-feedback.txt", 0);
    coupling_shader_plan_post = coupling_read_float("data/shader-plan-post.txt", 0);
    coupling_shader_plan_temporal_ratio = coupling_read_float("data/shader-plan-temporal-ratio.txt", 0);
};

void() coupling_apply_stimmung =
{
    coupling_effect_review_preset = coupling_read_effect_review_preset();

    // AoA rotation speed: faster with voice activity
    if (aoa_entity)
    {
        float base_rot = 0.0;
        float voice_boost = coupling_voice_active * 1.5;
        float audio_boost = coupling_audio_rms * 0.8 + coupling_audio_onset * 1.2;
        aoa_entity.screwm_spin_y = base_rot + voice_boost + audio_boost;
    }

    // Fog is only a depth cue here. Drift must shape entities/surfaces rather
    // than muddying the whole view with haze.
    float fog_density = 0.008 - coupling_energy * 0.004 + coupling_audio_rms * 0.002;
    localcmd(strcat(strcat("fog ", ftos(fog_density)), " 0.025 0.018 0.032\n"));

    // Post-processing modulation from cognitive state. These are spatial
    // scroom fields, not fourth-wall camera filters.
    if (coupling_effect_review_preset >= 6.5)
    {
        coupling_apply_effect_review_preset();
        return;
    }

    float density_grounding = coupling_clamp_range(coupling_max2(coupling_effect_drift_density * 1.6, coupling_effect_drift_density_currency * 1.25), 0, 0.34);
    float drift_baseline = coupling_clamp_range(0.42 + coupling_effect_drift_active_ratio * 0.18 + coupling_effect_drift_active_effect_ratio * 0.20 + coupling_effect_drift_kind_variance * 0.24 + coupling_effect_drift_max_delta * 0.16 + density_grounding + coupling_visual_chain_param_pressure * 0.08, 0.36, 1.00);
    float fast_jitter = 0.5 + sin(time * (1.55 + coupling_effect_drift_fast_ratio * 1.15) + coupling_effect_drift_region_count * 5.6) * 0.5;
    float slow_jitter = 0.5 + sin(time * (0.17 + coupling_effect_drift_slow_ratio * 0.18) + coupling_effect_drift_tonal * 3.1 + coupling_effect_drift_kind_variance * 2.4) * 0.5;
    float family_mutation = coupling_clamp_range(coupling_effect_drift_active_slot_ratio * 0.35 + coupling_effect_drift_kind_variance * 0.45 + coupling_effect_drift_fast_ratio * 0.20, 0, 1);
    float local_motion = coupling_max2(coupling_local_warp, coupling_local_fisheye);
    local_motion = coupling_max2(local_motion, coupling_local_transform);
    local_motion = coupling_max2(local_motion, coupling_local_displacement);
    local_motion = coupling_max2(local_motion, coupling_local_droste);
    local_motion = coupling_max2(local_motion, coupling_local_tunnel);
    local_motion = coupling_max2(local_motion, coupling_local_tile);
    local_motion = coupling_max2(local_motion, coupling_local_drift);
    local_motion = coupling_max2(local_motion, coupling_local_breathing);
    local_motion = coupling_max2(local_motion, coupling_shader_plan_motion);
    float local_signal = coupling_max2(coupling_local_count, coupling_shader_plan_color);
    local_signal = coupling_max2(local_signal, coupling_shader_plan_feedback);
    local_signal = coupling_max2(local_signal, coupling_shader_plan_post);
    float temporal_signal = coupling_max2(coupling_effect_drift_temporal, coupling_shader_plan_temporal_ratio);
    float mode_tonal = coupling_effect_mode_tonal;
    float mode_atmospheric = coupling_effect_mode_atmospheric;
    float mode_temporal = coupling_effect_mode_temporal;
    float mode_texture = coupling_effect_mode_texture;
    float mode_edge = coupling_effect_mode_edge;
    float mode_compositing = coupling_effect_mode_compositing;
    if (coupling_effect_drift_tonal <= 0.01)
        mode_tonal = 0;
    if (coupling_effect_drift_atmospheric <= 0.01)
        mode_atmospheric = 0;
    if (temporal_signal <= 0.01)
        mode_temporal = 0;
    if (coupling_effect_drift_texture <= 0.01)
        mode_texture = 0;
    if (coupling_effect_drift_edge <= 0.01)
        mode_edge = 0;
    if (coupling_effect_drift_compositing <= 0.01)
        mode_compositing = 0;

    // UserVec1: room_absorption, prismatic_drift, temperature_bias, dust
    float vig = coupling_clamp_range(0.015 + coupling_effect_drift_atmospheric * 0.035 + slow_jitter * 0.012, 0.000, 0.085);
    float ca = coupling_clamp_range(0.72 + coupling_voice_active * 0.12 + coupling_reverie_spectral * 0.24 + coupling_effect_drift_atmospheric * 1.55 + coupling_visual_chain_color * 0.38 + fast_jitter * 0.54 + coupling_effect_drift_compositing * 0.56 + local_motion * 0.58 + local_signal * 0.20 + family_mutation * 0.48, 0.28, 4.80);
    float temp_val = coupling_clamp_range(coupling_reverie_salience * 0.018 + coupling_effect_drift_tonal * 0.08 + coupling_visual_chain_color * 0.045 + family_mutation * 0.035, 0, 0.18);
    if (mode_tonal > 0.82)
        temp_val = coupling_clamp_range(temp_val + 0.05 + slow_jitter * 0.04, 0, 0.24);
    float grain_val = 0.0;
    grain_val = coupling_clamp_range(grain_val + coupling_effect_drift_texture * 0.0009 + temporal_signal * 0.0008 + local_signal * 0.0006 + fast_jitter * 0.0007, 0.000, 0.0045);

    // UserVec2: signal_aura, edge_glow, posterize, sharpen
    float scan_val = coupling_clamp_range(0.24 + coupling_reverie_trace * 0.08 + coupling_audio_onset * 0.02 + coupling_effect_drift_max_delta * 0.34 + coupling_effect_drift_compositing * 0.56 + coupling_shader_plan_feedback * 0.22 + local_signal * 0.16 + fast_jitter * 0.24 + family_mutation * 0.42, 0.08, 1.80);
    if (mode_compositing > 0.38 && mode_compositing < 0.55)
        scan_val = coupling_clamp_range(scan_val + 0.32 + fast_jitter * 0.26, 0.12, 1.55);
    float edge_val = coupling_clamp_range(0.38 + coupling_energy * 0.05 + coupling_reverie_salience * 0.14 + coupling_audio_onset * 0.04 + coupling_effect_drift_edge * 1.64 + coupling_effect_drift_active_ratio * 0.34 + coupling_effect_drift_kind_variance * 0.42 + coupling_shader_plan_post * 0.20 + fast_jitter * 0.22, 0.18, 3.10);
    float poster_val = mode_texture;
    if (mode_tonal > 0.68)
        poster_val = coupling_clamp_range(5 + coupling_effect_drift_tonal * 4 + fast_jitter * 3, 4, 12);
    float sharpen_val = coupling_clamp_range(0.03 + coupling_reverie_salience * 0.05 + coupling_audio_onset * 0.03 + coupling_effect_drift_edge * 0.16 + coupling_effect_drift_texture * 0.08, 0.01, 0.32);

    // UserVec3: spatial_warp, signal_noise, halftone, threshold.
    float warp_val = coupling_clamp_range(coupling_reverie_trace * 0.006 + coupling_reverie_temporal * 0.004 + coupling_audio_onset * 0.002 + coupling_visual_chain_drift * 0.030 + coupling_effect_drift_atmospheric * 0.052 + temporal_signal * 0.040 + local_motion * 0.056 + fast_jitter * 0.014 + family_mutation * 0.024, 0.000, 0.15);
    if (mode_temporal > 0.68)
        warp_val = coupling_clamp_range(warp_val + 0.018 + fast_jitter * 0.020, 0.006, 0.14);
    if (mode_atmospheric > 0.30 && mode_atmospheric < 0.42)
        warp_val = 0.0;
    if ((mode_atmospheric > 0.56 && mode_atmospheric < 0.66) || coupling_local_mirror > 0.55)
        warp_val = -coupling_clamp_range(0.035 + coupling_local_mirror * 0.080 + coupling_effect_drift_atmospheric * 0.040, 0.04, 0.13);
    if (mode_atmospheric > 0.44 && mode_atmospheric < 0.54)
        warp_val = coupling_clamp_range(0.055 + coupling_effect_drift_atmospheric * 0.060, 0.05, 0.16);
    float noise_val = 0.0;
    noise_val = coupling_clamp_range(noise_val + coupling_reverie_temporal * 0.0005 + coupling_effect_drift_texture * 0.0038 + temporal_signal * 0.0048 + coupling_shader_plan_feedback * 0.003 + local_signal * 0.001 + fast_jitter * 0.0018 + family_mutation * 0.0025, 0.000, 0.024);
    if (mode_temporal > 0.90 || mode_texture > 0.92)
        noise_val = coupling_clamp_range(noise_val + 0.006 + fast_jitter * 0.006, 0.002, 0.034);
    float halftone_val = 0;
    if (mode_texture > 0.58 && mode_texture < 0.74)
        halftone_val = coupling_clamp_range(4 + coupling_effect_drift_texture * 5 + slow_jitter * 4, 3, 13);
    float threshold_val = 0;
    if ((mode_edge > 0.72 && coupling_effect_drift_max_delta > 0.45) || mode_texture > 0.96 || mode_compositing > 0.84)
        threshold_val = coupling_clamp_range(0.02 + coupling_effect_drift_edge * 0.08 + fast_jitter * 0.06, 0, 0.18);

    // UserVec4: material emboss, inversion pressure, aperture mask, thermal.
    float emboss_val = coupling_clamp_range(coupling_reverie_material * 0.08 + coupling_effect_drift_texture * 0.24 + coupling_effect_drift_edge * 0.18 + coupling_shader_plan_post * 0.10 + family_mutation * 0.10, 0, 0.54);
    if ((mode_atmospheric > 0.30 && mode_atmospheric < 0.42) || coupling_local_kaleidoscope > 0.55)
        emboss_val = -(4.0 + coupling_local_kaleidoscope * 6.0);
    float invert_val = coupling_clamp_range(coupling_reverie_inversion * 0.035 + coupling_reverie_temporal * 0.008 + coupling_effect_drift_compositing * 0.12 + coupling_effect_drift_max_delta * 0.06 * fast_jitter + coupling_shader_plan_feedback * 0.026, 0, 0.30);
    if (mode_tonal > 0.30 && mode_tonal < 0.42)
        invert_val = coupling_clamp_range(invert_val + 0.10, 0, 0.30);
    if (mode_compositing > 0.64 && mode_compositing < 0.78)
        invert_val = coupling_clamp_range(invert_val + 0.08 + slow_jitter * 0.06, 0, 0.32);
    float aperture_val = coupling_clamp_range(coupling_reverie_aperture * 0.14 + coupling_visual_chain_aperture * 0.12 + coupling_effect_drift_active_ratio * 0.04 * slow_jitter, 0, 0.24);
    float thermal_val = coupling_clamp_range(coupling_reverie_thermal * 0.08 + coupling_audio_onset * 0.012 + coupling_effect_drift_tonal * 0.14 + drift_baseline * 0.035, 0, 0.26);
    if (mode_tonal > 0.56 && mode_tonal < 0.68)
        thermal_val = coupling_clamp_range(thermal_val + 0.12, 0, 0.38);

    // Review presets 1-6 are additive expression floors for the AVSDLC matrix:
    // they keep live SlotDrift coupling but force each named row to actually
    // exercise its family instead of collapsing back to the generic drift field.
    if (coupling_effect_review_preset >= 0.5 && coupling_effect_review_preset < 1.5)
    {
        if (vig < 0.055)
            vig = 0.055;
        if (ca < 1.85)
            ca = 1.85;
        if (scan_val < 0.46)
            scan_val = 0.46;
        if (edge_val < 1.32)
            edge_val = 1.32;
        if (warp_val < 0.035)
            warp_val = 0.035;
        if (noise_val < 0.070)
            noise_val = 0.070;
        if (sharpen_val < 0.10)
            sharpen_val = 0.10;
    }
    else if (coupling_effect_review_preset >= 1.5 && coupling_effect_review_preset < 2.5)
    {
        if (ca < 3.35)
            ca = 3.35;
        if (temp_val < 0.05)
            temp_val = 0.05;
        if (scan_val < 1.05)
            scan_val = 1.05;
        if (edge_val < 2.10)
            edge_val = 2.10;
        if (warp_val < 0.050)
            warp_val = 0.050;
        if (noise_val < 0.090)
            noise_val = 0.090;
        if (invert_val < 0.03)
            invert_val = 0.03;
        if (sharpen_val < 0.14)
            sharpen_val = 0.14;
    }
    else if (coupling_effect_review_preset >= 2.5 && coupling_effect_review_preset < 3.5)
    {
        if (vig < 0.065)
            vig = 0.065;
        if (ca < 2.30)
            ca = 2.30;
        if (grain_val < 0.055)
            grain_val = 0.055;
        if (scan_val < 0.85)
            scan_val = 0.85;
        if (edge_val < 1.60)
            edge_val = 1.60;
        if (warp_val < 0.075)
            warp_val = 0.075;
        if (noise_val < 0.160)
            noise_val = 0.160;
    }
    else if (coupling_effect_review_preset >= 3.5 && coupling_effect_review_preset < 4.5)
    {
        if (ca < 2.00)
            ca = 2.00;
        if (scan_val < 0.80)
            scan_val = 0.80;
        if (edge_val < 1.55)
            edge_val = 1.55;
        if (poster_val < 7)
            poster_val = 7;
        if (halftone_val < 7)
            halftone_val = 7;
        if (noise_val < 0.090)
            noise_val = 0.090;
        if (threshold_val < 0.045)
            threshold_val = 0.045;
        if (sharpen_val < 0.12)
            sharpen_val = 0.12;
    }
    else if (coupling_effect_review_preset >= 4.5 && coupling_effect_review_preset < 5.5)
    {
        if (ca < 2.10)
            ca = 2.10;
        if (temp_val < 0.12)
            temp_val = 0.12;
        if (scan_val < 0.70)
            scan_val = 0.70;
        if (edge_val < 1.95)
            edge_val = 1.95;
        if (noise_val < 0.090)
            noise_val = 0.090;
        if (emboss_val < 0.36)
            emboss_val = 0.36;
        if (aperture_val < 0.13)
            aperture_val = 0.13;
        if (thermal_val < 0.32)
            thermal_val = 0.32;
    }
    else if (coupling_effect_review_preset >= 5.5 && coupling_effect_review_preset < 6.5)
    {
        if (ca < 1.85)
            ca = 1.85;
        if (scan_val < 0.65)
            scan_val = 0.65;
        if (edge_val < 1.55)
            edge_val = 1.55;
        if (warp_val < 0.040)
            warp_val = 0.040;
        if (noise_val < 0.120)
            noise_val = 0.120;
        if (threshold_val < 0.13)
            threshold_val = 0.13;
        if (invert_val < 0.20)
            invert_val = 0.20;
        if (aperture_val < 0.08)
            aperture_val = 0.08;
        if (thermal_val < 0.16)
            thermal_val = 0.16;
    }

    coupling_write_uservecs(
        vig, ca, temp_val, grain_val,
        scan_val, edge_val, poster_val, sharpen_val,
        warp_val, noise_val, halftone_val, threshold_val,
        emboss_val, invert_val, aperture_val, thermal_val
    );
};

void() coupling_check_working_mode =
{
    if (time < coupling_mode_check_next)
        return;
    coupling_mode_check_next = time + 5.0;

    // Path resolved at runtime via cvar set by systemd unit Environment
    float fh = fopen("data/working-mode.txt", FILE_READ);
    if (fh < 0)
        return;
    string line = fgets(fh);
    fclose(fh);
    if (!line)
        return;

    if (line == coupling_current_mode)
        return;

    coupling_current_mode = line;
    if (line == "rnd" || line == "research")
    {
        string map_name = strcat("screwm-", line);
        dprint(strcat(strcat("Working mode changed to: ", line), "\n"));
        localcmd(strcat(strcat("map ", map_name), "\n"));
    }
    else
    {
        dprint(strcat(strcat("Ignoring unsupported Screwm working mode: ", line), "\n"));
    }
};

void() coupling_tick =
{
    if (time < coupling_next_poll)
        return;

    coupling_next_poll = time + coupling_poll_interval;
    coupling_read_stimmung();
    coupling_read_voice();
    coupling_read_reverie();
    coupling_read_audio();
    coupling_read_effect_drift();
    coupling_read_local_effects();
    coupling_apply_stimmung();
    coupling_check_working_mode();
};
