// Screwm CSQC - in-engine ward identity, drift links, and state lighting.

float screwm_width;
float screwm_height;
float screwm_next_poll;
float screwm_energy;
float screwm_voice;
float screwm_audio_rms;
float screwm_audio_onset;
float screwm_reverie_temporal;
float screwm_reverie_spectral;
float screwm_reverie_material;
float screwm_reverie_thermal;
float screwm_homage_quake;
float screwm_homage_transition;
float screwm_homage_hue;
float screwm_homage_signature;
float screwm_homage_rotation;
float screwm_visual_zone_01;
float screwm_visual_zone_02;
float screwm_visual_zone_03;
float screwm_visual_zone_04;
float screwm_visual_zone_05;
float screwm_visual_zone_06;
float screwm_visual_zone_07;
float screwm_visual_zone_08;
float screwm_visual_display;
float screwm_visual_stance;
float screwm_visual_turbulence;
float screwm_visual_brightness;
float screwm_visual_warmth;
float screwm_stimmung_health;
float screwm_stimmung_resource;
float screwm_stimmung_error;
float screwm_stimmung_audience;
float screwm_stimmung_operator_energy;
float screwm_chain_01;
float screwm_chain_02;
float screwm_chain_03;
float screwm_chain_04;
float screwm_chain_05;
float screwm_chain_06;
float screwm_chain_07;
float screwm_chain_08;
float screwm_chain_09;
float screwm_chain_noise;
float screwm_chain_drift;
float screwm_chain_color;
float screwm_chain_feedback;
float screwm_chain_aperture;
float screwm_chain_param_pressure;
float screwm_effect_drift_pass_count;
float screwm_effect_drift_active_ratio;
float screwm_effect_drift_active_slot_ratio;
float screwm_effect_drift_active_effect_ratio;
float screwm_effect_drift_fast_ratio;
float screwm_effect_drift_slow_ratio;
float screwm_effect_drift_kind_variance;
float screwm_effect_drift_max_delta;
float screwm_effect_drift_region_count;
float screwm_effect_drift_tonal;
float screwm_effect_drift_atmospheric;
float screwm_effect_drift_temporal;
float screwm_effect_drift_texture;
float screwm_effect_drift_edge;
float screwm_effect_drift_compositing;
float screwm_effect_drift_density;
float screwm_effect_drift_density_currency;
float screwm_effect_mode_tonal;
float screwm_effect_mode_atmospheric;
float screwm_effect_mode_temporal;
float screwm_effect_mode_texture;
float screwm_effect_mode_edge;
float screwm_effect_mode_compositing;
float screwm_imagination_salience;
float screwm_imagination_continuation;
float screwm_imagination_material;
float screwm_imagination_dim_01;
float screwm_imagination_dim_02;
float screwm_imagination_dim_03;
float screwm_imagination_dim_04;
float screwm_imagination_dim_05;
float screwm_imagination_dim_06;
float screwm_imagination_dim_07;
float screwm_imagination_dim_08;
float screwm_imagination_dim_09;
string screwm_mode;
string screwm_w01;
string screwm_w02;
string screwm_w03;
string screwm_w04;
string screwm_w05;
string screwm_w06;
string screwm_w07;
string screwm_w08;
string screwm_w09;
string screwm_w10;
string screwm_w11;
string screwm_w12;
string screwm_w13;
string screwm_w14;
string screwm_w15;
string screwm_w16;
string screwm_w17;
string screwm_w18;
string screwm_w19;
string screwm_w20;
string screwm_w21;
string screwm_w22;
string screwm_w23;
string screwm_w24;
string screwm_w25;
string screwm_w26;
string screwm_w27;
string screwm_w28;
string screwm_w29;
string screwm_w30;
string screwm_w31;
string screwm_w32;
string screwm_w33;
string screwm_w34;
string screwm_w35;
string screwm_w36;
float screwm_active_01;
float screwm_active_02;
float screwm_active_03;
float screwm_active_04;
float screwm_active_05;
float screwm_active_06;
float screwm_active_07;
float screwm_active_08;
float screwm_active_09;
float screwm_active_10;
float screwm_active_11;
float screwm_active_12;
float screwm_active_13;
float screwm_active_14;
float screwm_active_15;
float screwm_active_16;
float screwm_active_17;
float screwm_active_18;
float screwm_active_19;
float screwm_active_20;
float screwm_active_21;
float screwm_active_22;
float screwm_active_23;
float screwm_active_24;
float screwm_active_25;
float screwm_active_26;
float screwm_active_27;
float screwm_active_28;
float screwm_active_29;
float screwm_active_30;
float screwm_active_31;
float screwm_active_32;
float screwm_active_33;
float screwm_active_34;
float screwm_active_35;
float screwm_active_36;
float screwm_presence_01;
float screwm_presence_02;
float screwm_presence_03;
float screwm_presence_04;
float screwm_presence_05;
float screwm_presence_06;
float screwm_presence_07;
float screwm_presence_08;
float screwm_presence_09;
float screwm_presence_10;
float screwm_presence_11;
float screwm_presence_12;
float screwm_presence_13;
float screwm_presence_14;
float screwm_presence_15;
float screwm_presence_16;
float screwm_presence_17;
float screwm_presence_18;
float screwm_presence_19;
float screwm_presence_20;
float screwm_presence_21;
float screwm_presence_22;
float screwm_presence_23;
float screwm_presence_24;
float screwm_presence_25;
float screwm_presence_26;
float screwm_presence_27;
float screwm_presence_28;
float screwm_presence_29;
float screwm_presence_30;
float screwm_presence_31;
float screwm_presence_32;
float screwm_presence_33;
float screwm_presence_34;
float screwm_presence_35;
float screwm_presence_36;
float screwm_ward_property_active_ratio;
float screwm_ward_property_depth_pressure;
float screwm_ward_property_glow_pressure;
float screwm_ward_property_front_pressure;
float screwm_ward_property_drift_pressure;
float screwm_ward_property_presence_pressure;
float screwm_ward_property_fishbowl_pressure;
float screwm_source_priority_01;
float screwm_source_priority_02;
float screwm_source_priority_03;
float screwm_source_priority_04;
float screwm_source_priority_05;
float screwm_source_priority_06;
float screwm_source_fresh_01;
float screwm_source_fresh_02;
float screwm_source_fresh_03;
float screwm_source_fresh_04;
float screwm_source_fresh_05;
float screwm_source_fresh_06;
float screwm_content_source_count;
float screwm_content_fresh_01;
float screwm_content_fresh_02;
float screwm_content_fresh_03;
float screwm_content_fresh_04;
float screwm_content_fresh_05;
float screwm_content_fresh_06;
float screwm_content_opacity_01;
float screwm_content_opacity_02;
float screwm_content_opacity_03;
float screwm_content_opacity_04;
float screwm_content_opacity_05;
float screwm_content_opacity_06;
float screwm_content_area_01;
float screwm_content_area_02;
float screwm_content_area_03;
float screwm_content_area_04;
float screwm_content_area_05;
float screwm_content_area_06;
float screwm_aoa_pane_01;
float screwm_aoa_pane_02;
float screwm_aoa_pane_03;
float screwm_aoa_pane_04;
float screwm_aoa_pane_05;
float screwm_aoa_pane_06;
float screwm_aoa_pane_07;
float screwm_aoa_pane_08;
float screwm_aoa_pane_09;
float screwm_aoa_pane_10;
float screwm_effect_01;
float screwm_effect_02;
float screwm_effect_03;
float screwm_effect_04;
float screwm_effect_05;
float screwm_effect_06;
float screwm_effect_07;
float screwm_effect_08;
float screwm_effect_09;
float screwm_effect_10;
float screwm_effect_11;
float screwm_shader_plan_pass_count;
float screwm_shader_plan_render_ratio;
float screwm_shader_plan_temporal_ratio;
float screwm_shader_plan_color;
float screwm_shader_plan_motion;
float screwm_shader_plan_feedback;
float screwm_shader_plan_post;
float screwm_gem_recruitment_score;
float screwm_gem_recruitment_fresh;
float screwm_gem_frame_fresh;
float screwm_gem_frame_count;
float screwm_gem_layer_density;
float screwm_gem_layer_opacity;
float screwm_gem_hold_pressure;
float screwm_gem_narrative_pressure;
float screwm_impingement_count;
float screwm_impingement_strength;
float screwm_impingement_fresh;
float screwm_impingement_curiosity;
float screwm_impingement_reverie_alert;
float screwm_recruitment_family_count;
float screwm_recruitment_fresh_ratio;
float screwm_recruitment_score;
float screwm_recruitment_transition_pressure;
float screwm_recruitment_studio_pressure;
float screwm_programme_role;
float screwm_programme_beat_progress;
float screwm_programme_beat_index;
float screwm_programme_duration_pressure;
float screwm_programme_source_pressure;
float screwm_programme_asset_pressure;
float screwm_programme_affordance_pressure;
float screwm_programme_cue_hold;
float screwm_live_token_pressure;
float screwm_live_viewer_pressure;
float screwm_live_token_burst;
float screwm_live_album_confidence;
float screwm_live_album_fresh;
float screwm_live_album_playing;
float screwm_live_album_risk;
float screwm_live_voice_active;
float screwm_governance_consent_allowed;
float screwm_governance_persistence_allowed;
float screwm_governance_health_reference;
float screwm_governance_health_perception;
float screwm_governance_health_error;
float screwm_governance_health_fresh;
float screwm_governance_follow_active;
float screwm_governance_follow_confidence;
float screwm_governance_follow_fresh;

// Desaturated baseline lighting (Moksha palette law): the void is lit by a
// dim, low-chroma key/rim/fill, NOT saturated neon. These are additive dlight
// colors — magnitude IS intensity, so low+near-neutral values dim AND desaturate
// the wash that was reading as colored "beams". Standing-neon is reserved for
// flagged accents only (see screwm_accent_*), never the baseline flood.
vector screwm_cyan = '0.26 0.34 0.38';
vector screwm_amber = '0.38 0.32 0.26';
vector screwm_rose = '0.36 0.28 0.32';
vector screwm_green = '0.30 0.36 0.28';
vector screwm_dim = '0.10 0.13 0.14';
vector screwm_review_camera_origin;
vector screwm_review_camera_angles;
vector screwm_review_camera_fov;
float screwm_review_camera_period;
float screwm_review_camera_two_pi;
float screwm_review_camera_manual_until;
vector screwm_native_last_angles;
float screwm_native_angles_ready;

string(string path, string fallback) screwm_read_line =
{
    float fh;
    string line;

    fh = fopen(path, FILE_READ);
    if (fh < 0)
        return fallback;

    line = fgets(fh);
    fclose(fh);
    if (line)
        return line;

    return fallback;
};

float(float value, float low, float high) screwm_clamp =
{
    if (value < low)
        return low;
    if (value > high)
        return high;
    return value;
};

float(float a, float b) screwm_max2 =
{
    if (a > b)
        return a;
    return b;
};

float(float value) screwm_abs =
{
    if (value < 0)
        return 0 - value;
    return value;
};

vector(float phase) screwm_synthwave_color =
{
    vector color;

    // Desaturated, near-neutral roaming color with only a FAINT slow hue/sat
    // transit (anti_visualizer: brightness ~frozen, channels kept close so the
    // result is cool-grey "always-transiting shallows", not a saturated synthwave
    // disco sweep). Small sin amplitudes => low chroma; convergent means => grey.
    color = '0 0 0';
    color_x = screwm_clamp(0.34 + 0.09 * sin(phase), 0.20, 0.50);
    color_y = screwm_clamp(0.38 + 0.07 * sin(phase + 2.094), 0.24, 0.52);
    color_z = screwm_clamp(0.42 + 0.09 * sin(phase + 4.188), 0.26, 0.56);
    return color;
};

float(string path) screwm_read_norm =
{
    string line;

    line = screwm_read_line(path, "0");
    return screwm_clamp(stof(line), 0, 1);
};

float(string path, float fallback) screwm_read_float =
{
    string line;

    line = screwm_read_line(path, ftos(fallback));
    return stof(line);
};

void() screwm_poll_state =
{
    string line;

    if (time < screwm_next_poll)
        return;
    screwm_next_poll = time + 0.5;

    screwm_mode = screwm_read_line("data/working-mode.txt", "rnd");

    line = screwm_read_line("data/stimmung-energy.txt", "0.5");
    screwm_energy = screwm_clamp(stof(line), 0, 1);

    line = screwm_read_line("data/voice-active.txt", "0");
    screwm_voice = screwm_clamp(stof(line), 0, 1);
    screwm_audio_rms = screwm_read_norm("data/audio-rms.txt");
    screwm_audio_onset = screwm_read_norm("data/audio-onset.txt");
    screwm_reverie_temporal = screwm_read_norm("data/reverie-temporal.txt");
    screwm_reverie_spectral = screwm_read_norm("data/reverie-spectral.txt");
    screwm_reverie_material = screwm_read_norm("data/reverie-material.txt");
    screwm_reverie_thermal = screwm_read_norm("data/reverie-thermal.txt");
    screwm_homage_quake = screwm_read_norm("data/homage-quake-active.txt");
    screwm_homage_transition = screwm_read_norm("data/homage-transition-energy.txt");
    screwm_homage_hue = screwm_read_norm("data/homage-accent-hue.txt");
    screwm_homage_signature = screwm_read_norm("data/homage-signature-intensity.txt");
    screwm_homage_rotation = screwm_read_norm("data/homage-rotation-phase.txt");
    screwm_visual_zone_01 = screwm_read_norm("data/visual-zone-01.txt");
    screwm_visual_zone_02 = screwm_read_norm("data/visual-zone-02.txt");
    screwm_visual_zone_03 = screwm_read_norm("data/visual-zone-03.txt");
    screwm_visual_zone_04 = screwm_read_norm("data/visual-zone-04.txt");
    screwm_visual_zone_05 = screwm_read_norm("data/visual-zone-05.txt");
    screwm_visual_zone_06 = screwm_read_norm("data/visual-zone-06.txt");
    screwm_visual_zone_07 = screwm_read_norm("data/visual-zone-07.txt");
    screwm_visual_zone_08 = screwm_read_norm("data/visual-zone-08.txt");
    screwm_visual_display = screwm_read_norm("data/visual-display-state.txt");
    screwm_visual_stance = screwm_read_norm("data/visual-stance.txt");
    screwm_visual_turbulence = screwm_read_norm("data/visual-ambient-turbulence.txt");
    screwm_visual_brightness = screwm_read_norm("data/visual-ambient-brightness.txt");
    screwm_visual_warmth = screwm_read_norm("data/visual-ambient-warmth.txt");
    screwm_stimmung_health = screwm_read_norm("data/stimmung-health.txt");
    screwm_stimmung_resource = screwm_read_norm("data/stimmung-resource.txt");
    screwm_stimmung_error = screwm_read_norm("data/stimmung-error.txt");
    screwm_stimmung_audience = screwm_read_norm("data/stimmung-audience.txt");
    screwm_stimmung_operator_energy = screwm_read_norm("data/stimmung-operator-energy.txt");
    screwm_chain_01 = screwm_read_norm("data/visual-chain-01.txt");
    screwm_chain_02 = screwm_read_norm("data/visual-chain-02.txt");
    screwm_chain_03 = screwm_read_norm("data/visual-chain-03.txt");
    screwm_chain_04 = screwm_read_norm("data/visual-chain-04.txt");
    screwm_chain_05 = screwm_read_norm("data/visual-chain-05.txt");
    screwm_chain_06 = screwm_read_norm("data/visual-chain-06.txt");
    screwm_chain_07 = screwm_read_norm("data/visual-chain-07.txt");
    screwm_chain_08 = screwm_read_norm("data/visual-chain-08.txt");
    screwm_chain_09 = screwm_read_norm("data/visual-chain-09.txt");
    screwm_chain_noise = screwm_read_norm("data/visual-chain-noise.txt");
    screwm_chain_drift = screwm_read_norm("data/visual-chain-drift.txt");
    screwm_chain_color = screwm_read_norm("data/visual-chain-color.txt");
    screwm_chain_feedback = screwm_read_norm("data/visual-chain-feedback.txt");
    screwm_chain_aperture = screwm_read_norm("data/visual-chain-aperture.txt");
    screwm_chain_param_pressure = screwm_read_norm("data/visual-chain-param-pressure.txt");
    screwm_effect_drift_pass_count = screwm_read_norm("data/effect-drift-pass-count.txt");
    screwm_effect_drift_active_ratio = screwm_read_norm("data/effect-drift-active-ratio.txt");
    screwm_effect_drift_active_slot_ratio = screwm_read_norm("data/effect-drift-active-slot-ratio.txt");
    screwm_effect_drift_active_effect_ratio = screwm_read_norm("data/effect-drift-active-effect-ratio.txt");
    screwm_effect_drift_fast_ratio = screwm_read_norm("data/effect-drift-fast-ratio.txt");
    screwm_effect_drift_slow_ratio = screwm_read_norm("data/effect-drift-slow-ratio.txt");
    screwm_effect_drift_kind_variance = screwm_read_norm("data/effect-drift-kind-variance.txt");
    screwm_effect_drift_max_delta = screwm_read_norm("data/effect-drift-max-delta.txt");
    screwm_effect_drift_region_count = screwm_read_norm("data/effect-drift-region-count.txt");
    screwm_effect_drift_tonal = screwm_read_norm("data/effect-drift-tonal.txt");
    screwm_effect_drift_atmospheric = screwm_read_norm("data/effect-drift-atmospheric.txt");
    screwm_effect_drift_temporal = screwm_read_norm("data/effect-drift-temporal.txt");
    screwm_effect_drift_texture = screwm_read_norm("data/effect-drift-texture.txt");
    screwm_effect_drift_edge = screwm_read_norm("data/effect-drift-edge.txt");
    screwm_effect_drift_compositing = screwm_read_norm("data/effect-drift-compositing.txt");
    screwm_effect_drift_density = screwm_read_norm("data/effect-drift-density.txt");
    screwm_effect_drift_density_currency = screwm_read_norm("data/effect-drift-density-currency.txt");
    screwm_effect_mode_tonal = screwm_read_norm("data/effect-drift-mode-tonal.txt");
    screwm_effect_mode_atmospheric = screwm_read_norm("data/effect-drift-mode-atmospheric.txt");
    screwm_effect_mode_temporal = screwm_read_norm("data/effect-drift-mode-temporal.txt");
    screwm_effect_mode_texture = screwm_read_norm("data/effect-drift-mode-texture.txt");
    screwm_effect_mode_edge = screwm_read_norm("data/effect-drift-mode-edge.txt");
    screwm_effect_mode_compositing = screwm_read_norm("data/effect-drift-mode-compositing.txt");
    screwm_imagination_salience = screwm_read_norm("data/imagination-salience.txt");
    screwm_imagination_continuation = screwm_read_norm("data/imagination-continuation.txt");
    screwm_imagination_material = screwm_read_norm("data/imagination-material.txt");
    screwm_imagination_dim_01 = screwm_read_norm("data/imagination-dim-01.txt");
    screwm_imagination_dim_02 = screwm_read_norm("data/imagination-dim-02.txt");
    screwm_imagination_dim_03 = screwm_read_norm("data/imagination-dim-03.txt");
    screwm_imagination_dim_04 = screwm_read_norm("data/imagination-dim-04.txt");
    screwm_imagination_dim_05 = screwm_read_norm("data/imagination-dim-05.txt");
    screwm_imagination_dim_06 = screwm_read_norm("data/imagination-dim-06.txt");
    screwm_imagination_dim_07 = screwm_read_norm("data/imagination-dim-07.txt");
    screwm_imagination_dim_08 = screwm_read_norm("data/imagination-dim-08.txt");
    screwm_imagination_dim_09 = screwm_read_norm("data/imagination-dim-09.txt");

    screwm_w01 = screwm_read_line("data/ward-01.txt", "");
    screwm_w02 = screwm_read_line("data/ward-02.txt", "");
    screwm_w03 = screwm_read_line("data/ward-03.txt", "");
    screwm_w04 = screwm_read_line("data/ward-04.txt", "");
    screwm_w05 = screwm_read_line("data/ward-05.txt", "");
    screwm_w06 = screwm_read_line("data/ward-06.txt", "");
    screwm_w07 = screwm_read_line("data/ward-07.txt", "");
    screwm_w08 = screwm_read_line("data/ward-08.txt", "");
    screwm_w09 = screwm_read_line("data/ward-09.txt", "");
    screwm_w10 = screwm_read_line("data/ward-10.txt", "");
    screwm_w11 = screwm_read_line("data/ward-11.txt", "");
    screwm_w12 = screwm_read_line("data/ward-12.txt", "");
    screwm_w13 = screwm_read_line("data/ward-13.txt", "");
    screwm_w14 = screwm_read_line("data/ward-14.txt", "");
    screwm_w15 = screwm_read_line("data/ward-15.txt", "");
    screwm_w16 = screwm_read_line("data/ward-16.txt", "");
    screwm_w17 = screwm_read_line("data/ward-17.txt", "");
    screwm_w18 = screwm_read_line("data/ward-18.txt", "");
    screwm_w19 = screwm_read_line("data/ward-19.txt", "");
    screwm_w20 = screwm_read_line("data/ward-20.txt", "");
    screwm_w21 = screwm_read_line("data/ward-21.txt", "");
    screwm_w22 = screwm_read_line("data/ward-22.txt", "");
    screwm_w23 = screwm_read_line("data/ward-23.txt", "");
    screwm_w24 = screwm_read_line("data/ward-24.txt", "");
    screwm_w25 = screwm_read_line("data/ward-25.txt", "");
    screwm_w26 = screwm_read_line("data/ward-26.txt", "");
    screwm_w27 = screwm_read_line("data/ward-27.txt", "");
    screwm_w28 = screwm_read_line("data/ward-28.txt", "");
    screwm_w29 = screwm_read_line("data/ward-29.txt", "");
    screwm_w30 = screwm_read_line("data/ward-30.txt", "");
    screwm_w31 = screwm_read_line("data/ward-31.txt", "");
    screwm_w32 = screwm_read_line("data/ward-32.txt", "");
    screwm_w33 = screwm_read_line("data/ward-33.txt", "");
    screwm_w34 = screwm_read_line("data/ward-34.txt", "");
    screwm_w35 = screwm_read_line("data/ward-35.txt", "");
    screwm_w36 = screwm_read_line("data/ward-36.txt", "");

    screwm_active_01 = screwm_read_norm("data/ward-active-01.txt");
    screwm_active_02 = screwm_read_norm("data/ward-active-02.txt");
    screwm_active_03 = screwm_read_norm("data/ward-active-03.txt");
    screwm_active_04 = screwm_read_norm("data/ward-active-04.txt");
    screwm_active_05 = screwm_read_norm("data/ward-active-05.txt");
    screwm_active_06 = screwm_read_norm("data/ward-active-06.txt");
    screwm_active_07 = screwm_read_norm("data/ward-active-07.txt");
    screwm_active_08 = screwm_read_norm("data/ward-active-08.txt");
    screwm_active_09 = screwm_read_norm("data/ward-active-09.txt");
    screwm_active_10 = screwm_read_norm("data/ward-active-10.txt");
    screwm_active_11 = screwm_read_norm("data/ward-active-11.txt");
    screwm_active_12 = screwm_read_norm("data/ward-active-12.txt");
    screwm_active_13 = screwm_read_norm("data/ward-active-13.txt");
    screwm_active_14 = screwm_read_norm("data/ward-active-14.txt");
    screwm_active_15 = screwm_read_norm("data/ward-active-15.txt");
    screwm_active_16 = screwm_read_norm("data/ward-active-16.txt");
    screwm_active_17 = screwm_read_norm("data/ward-active-17.txt");
    screwm_active_18 = screwm_read_norm("data/ward-active-18.txt");
    screwm_active_19 = screwm_read_norm("data/ward-active-19.txt");
    screwm_active_20 = screwm_read_norm("data/ward-active-20.txt");
    screwm_active_21 = screwm_read_norm("data/ward-active-21.txt");
    screwm_active_22 = screwm_read_norm("data/ward-active-22.txt");
    screwm_active_23 = screwm_read_norm("data/ward-active-23.txt");
    screwm_active_24 = screwm_read_norm("data/ward-active-24.txt");
    screwm_active_25 = screwm_read_norm("data/ward-active-25.txt");
    screwm_active_26 = screwm_read_norm("data/ward-active-26.txt");
    screwm_active_27 = screwm_read_norm("data/ward-active-27.txt");
    screwm_active_28 = screwm_read_norm("data/ward-active-28.txt");
    screwm_active_29 = screwm_read_norm("data/ward-active-29.txt");
    screwm_active_30 = screwm_read_norm("data/ward-active-30.txt");
    screwm_active_31 = screwm_read_norm("data/ward-active-31.txt");
    screwm_active_32 = screwm_read_norm("data/ward-active-32.txt");
    screwm_active_33 = screwm_read_norm("data/ward-active-33.txt");
    screwm_active_34 = screwm_read_norm("data/ward-active-34.txt");
    screwm_active_35 = screwm_read_norm("data/ward-active-35.txt");
    screwm_active_36 = screwm_read_norm("data/ward-active-36.txt");

    screwm_presence_01 = screwm_read_norm("data/ward-presence-01.txt");
    screwm_presence_02 = screwm_read_norm("data/ward-presence-02.txt");
    screwm_presence_03 = screwm_read_norm("data/ward-presence-03.txt");
    screwm_presence_04 = screwm_read_norm("data/ward-presence-04.txt");
    screwm_presence_05 = screwm_read_norm("data/ward-presence-05.txt");
    screwm_presence_06 = screwm_read_norm("data/ward-presence-06.txt");
    screwm_presence_07 = screwm_read_norm("data/ward-presence-07.txt");
    screwm_presence_08 = screwm_read_norm("data/ward-presence-08.txt");
    screwm_presence_09 = screwm_read_norm("data/ward-presence-09.txt");
    screwm_presence_10 = screwm_read_norm("data/ward-presence-10.txt");
    screwm_presence_11 = screwm_read_norm("data/ward-presence-11.txt");
    screwm_presence_12 = screwm_read_norm("data/ward-presence-12.txt");
    screwm_presence_13 = screwm_read_norm("data/ward-presence-13.txt");
    screwm_presence_14 = screwm_read_norm("data/ward-presence-14.txt");
    screwm_presence_15 = screwm_read_norm("data/ward-presence-15.txt");
    screwm_presence_16 = screwm_read_norm("data/ward-presence-16.txt");
    screwm_presence_17 = screwm_read_norm("data/ward-presence-17.txt");
    screwm_presence_18 = screwm_read_norm("data/ward-presence-18.txt");
    screwm_presence_19 = screwm_read_norm("data/ward-presence-19.txt");
    screwm_presence_20 = screwm_read_norm("data/ward-presence-20.txt");
    screwm_presence_21 = screwm_read_norm("data/ward-presence-21.txt");
    screwm_presence_22 = screwm_read_norm("data/ward-presence-22.txt");
    screwm_presence_23 = screwm_read_norm("data/ward-presence-23.txt");
    screwm_presence_24 = screwm_read_norm("data/ward-presence-24.txt");
    screwm_presence_25 = screwm_read_norm("data/ward-presence-25.txt");
    screwm_presence_26 = screwm_read_norm("data/ward-presence-26.txt");
    screwm_presence_27 = screwm_read_norm("data/ward-presence-27.txt");
    screwm_presence_28 = screwm_read_norm("data/ward-presence-28.txt");
    screwm_presence_29 = screwm_read_norm("data/ward-presence-29.txt");
    screwm_presence_30 = screwm_read_norm("data/ward-presence-30.txt");
    screwm_presence_31 = screwm_read_norm("data/ward-presence-31.txt");
    screwm_presence_32 = screwm_read_norm("data/ward-presence-32.txt");
    screwm_presence_33 = screwm_read_norm("data/ward-presence-33.txt");
    screwm_presence_34 = screwm_read_norm("data/ward-presence-34.txt");
    screwm_presence_35 = screwm_read_norm("data/ward-presence-35.txt");
    screwm_presence_36 = screwm_read_norm("data/ward-presence-36.txt");
    screwm_ward_property_active_ratio = screwm_read_norm("data/ward-property-active-ratio.txt");
    screwm_ward_property_depth_pressure = screwm_read_norm("data/ward-property-depth-pressure.txt");
    screwm_ward_property_glow_pressure = screwm_read_norm("data/ward-property-glow-pressure.txt");
    screwm_ward_property_front_pressure = screwm_read_norm("data/ward-property-front-pressure.txt");
    screwm_ward_property_drift_pressure = screwm_read_norm("data/ward-property-drift-pressure.txt");
    screwm_ward_property_presence_pressure = screwm_read_norm("data/ward-property-presence-pressure.txt");
    screwm_ward_property_fishbowl_pressure = screwm_read_norm("data/ward-property-fishbowl-pressure.txt");

    screwm_source_priority_01 = screwm_read_norm("data/source-priority-01.txt");
    screwm_source_priority_02 = screwm_read_norm("data/source-priority-02.txt");
    screwm_source_priority_03 = screwm_read_norm("data/source-priority-03.txt");
    screwm_source_priority_04 = screwm_read_norm("data/source-priority-04.txt");
    screwm_source_priority_05 = screwm_read_norm("data/source-priority-05.txt");
    screwm_source_priority_06 = screwm_read_norm("data/source-priority-06.txt");
    screwm_source_fresh_01 = screwm_read_norm("data/source-fresh-01.txt");
    screwm_source_fresh_02 = screwm_read_norm("data/source-fresh-02.txt");
    screwm_source_fresh_03 = screwm_read_norm("data/source-fresh-03.txt");
    screwm_source_fresh_04 = screwm_read_norm("data/source-fresh-04.txt");
    screwm_source_fresh_05 = screwm_read_norm("data/source-fresh-05.txt");
    screwm_source_fresh_06 = screwm_read_norm("data/source-fresh-06.txt");
    screwm_content_source_count = screwm_read_norm("data/content-source-count.txt");
    screwm_content_fresh_01 = screwm_read_norm("data/content-source-fresh-01.txt");
    screwm_content_fresh_02 = screwm_read_norm("data/content-source-fresh-02.txt");
    screwm_content_fresh_03 = screwm_read_norm("data/content-source-fresh-03.txt");
    screwm_content_fresh_04 = screwm_read_norm("data/content-source-fresh-04.txt");
    screwm_content_fresh_05 = screwm_read_norm("data/content-source-fresh-05.txt");
    screwm_content_fresh_06 = screwm_read_norm("data/content-source-fresh-06.txt");
    screwm_content_opacity_01 = screwm_read_norm("data/content-source-opacity-01.txt");
    screwm_content_opacity_02 = screwm_read_norm("data/content-source-opacity-02.txt");
    screwm_content_opacity_03 = screwm_read_norm("data/content-source-opacity-03.txt");
    screwm_content_opacity_04 = screwm_read_norm("data/content-source-opacity-04.txt");
    screwm_content_opacity_05 = screwm_read_norm("data/content-source-opacity-05.txt");
    screwm_content_opacity_06 = screwm_read_norm("data/content-source-opacity-06.txt");
    screwm_content_area_01 = screwm_read_norm("data/content-source-area-01.txt");
    screwm_content_area_02 = screwm_read_norm("data/content-source-area-02.txt");
    screwm_content_area_03 = screwm_read_norm("data/content-source-area-03.txt");
    screwm_content_area_04 = screwm_read_norm("data/content-source-area-04.txt");
    screwm_content_area_05 = screwm_read_norm("data/content-source-area-05.txt");
    screwm_content_area_06 = screwm_read_norm("data/content-source-area-06.txt");

    screwm_aoa_pane_01 = screwm_read_norm("data/aoa-pane-signal-01.txt");
    screwm_aoa_pane_02 = screwm_read_norm("data/aoa-pane-signal-02.txt");
    screwm_aoa_pane_03 = screwm_read_norm("data/aoa-pane-signal-03.txt");
    screwm_aoa_pane_04 = screwm_read_norm("data/aoa-pane-signal-04.txt");
    screwm_aoa_pane_05 = screwm_read_norm("data/aoa-pane-signal-05.txt");
    screwm_aoa_pane_06 = screwm_read_norm("data/aoa-pane-signal-06.txt");
    screwm_aoa_pane_07 = screwm_read_norm("data/aoa-pane-signal-07.txt");
    screwm_aoa_pane_08 = screwm_read_norm("data/aoa-pane-signal-08.txt");
    screwm_aoa_pane_09 = screwm_read_norm("data/aoa-pane-signal-09.txt");
    screwm_aoa_pane_10 = screwm_read_norm("data/aoa-pane-signal-10.txt");

    screwm_effect_01 = screwm_read_norm("data/local-effect-01.txt");
    screwm_effect_02 = screwm_read_norm("data/local-effect-02.txt");
    screwm_effect_03 = screwm_read_norm("data/local-effect-03.txt");
    screwm_effect_04 = screwm_read_norm("data/local-effect-04.txt");
    screwm_effect_05 = screwm_read_norm("data/local-effect-05.txt");
    screwm_effect_06 = screwm_read_norm("data/local-effect-06.txt");
    screwm_effect_07 = screwm_read_norm("data/local-effect-07.txt");
    screwm_effect_08 = screwm_read_norm("data/local-effect-08.txt");
    screwm_effect_09 = screwm_read_norm("data/local-effect-09.txt");
    screwm_effect_10 = screwm_read_norm("data/local-effect-10.txt");
    screwm_effect_11 = screwm_read_norm("data/local-effect-11.txt");
    screwm_shader_plan_pass_count = screwm_read_norm("data/shader-plan-pass-count.txt");
    screwm_shader_plan_render_ratio = screwm_read_norm("data/shader-plan-render-ratio.txt");
    screwm_shader_plan_temporal_ratio = screwm_read_norm("data/shader-plan-temporal-ratio.txt");
    screwm_shader_plan_color = screwm_read_norm("data/shader-plan-color.txt");
    screwm_shader_plan_motion = screwm_read_norm("data/shader-plan-motion.txt");
    screwm_shader_plan_feedback = screwm_read_norm("data/shader-plan-feedback.txt");
    screwm_shader_plan_post = screwm_read_norm("data/shader-plan-post.txt");
    screwm_gem_recruitment_score = screwm_read_norm("data/gem-recruitment-score.txt");
    screwm_gem_recruitment_fresh = screwm_read_norm("data/gem-recruitment-fresh.txt");
    screwm_gem_frame_fresh = screwm_read_norm("data/gem-frame-fresh.txt");
    screwm_gem_frame_count = screwm_read_norm("data/gem-frame-count.txt");
    screwm_gem_layer_density = screwm_read_norm("data/gem-layer-density.txt");
    screwm_gem_layer_opacity = screwm_read_norm("data/gem-layer-opacity.txt");
    screwm_gem_hold_pressure = screwm_read_norm("data/gem-hold-pressure.txt");
    screwm_gem_narrative_pressure = screwm_read_norm("data/gem-narrative-pressure.txt");
    screwm_impingement_count = screwm_read_norm("data/impingement-count.txt");
    screwm_impingement_strength = screwm_read_norm("data/impingement-strength.txt");
    screwm_impingement_fresh = screwm_read_norm("data/impingement-fresh.txt");
    screwm_impingement_curiosity = screwm_read_norm("data/impingement-curiosity.txt");
    screwm_impingement_reverie_alert = screwm_read_norm("data/impingement-reverie-alert.txt");
    screwm_recruitment_family_count = screwm_read_norm("data/recruitment-family-count.txt");
    screwm_recruitment_fresh_ratio = screwm_read_norm("data/recruitment-fresh-ratio.txt");
    screwm_recruitment_score = screwm_read_norm("data/recruitment-score.txt");
    screwm_recruitment_transition_pressure = screwm_read_norm("data/recruitment-transition-pressure.txt");
    screwm_recruitment_studio_pressure = screwm_read_norm("data/recruitment-studio-pressure.txt");
    screwm_programme_role = screwm_read_norm("data/programme-role.txt");
    screwm_programme_beat_progress = screwm_read_norm("data/programme-beat-progress.txt");
    screwm_programme_beat_index = screwm_read_norm("data/programme-beat-index.txt");
    screwm_programme_duration_pressure = screwm_read_norm("data/programme-duration-pressure.txt");
    screwm_programme_source_pressure = screwm_read_norm("data/programme-source-pressure.txt");
    screwm_programme_asset_pressure = screwm_read_norm("data/programme-asset-pressure.txt");
    screwm_programme_affordance_pressure = screwm_read_norm("data/programme-affordance-pressure.txt");
    screwm_programme_cue_hold = screwm_read_norm("data/programme-cue-hold.txt");
    screwm_live_token_pressure = screwm_read_norm("data/live-token-pressure.txt");
    screwm_live_viewer_pressure = screwm_read_norm("data/live-viewer-pressure.txt");
    screwm_live_token_burst = screwm_read_norm("data/live-token-burst.txt");
    screwm_live_album_confidence = screwm_read_norm("data/live-album-confidence.txt");
    screwm_live_album_fresh = screwm_read_norm("data/live-album-fresh.txt");
    screwm_live_album_playing = screwm_read_norm("data/live-album-playing.txt");
    screwm_live_album_risk = screwm_read_norm("data/live-album-risk.txt");
    screwm_live_voice_active = screwm_read_norm("data/live-voice-active.txt");
    screwm_governance_consent_allowed = screwm_read_norm("data/governance-consent-allowed.txt");
    screwm_governance_persistence_allowed = screwm_read_norm("data/governance-persistence-allowed.txt");
    screwm_governance_health_reference = screwm_read_norm("data/governance-health-reference.txt");
    screwm_governance_health_perception = screwm_read_norm("data/governance-health-perception.txt");
    screwm_governance_health_error = screwm_read_norm("data/governance-health-error.txt");
    screwm_governance_health_fresh = screwm_read_norm("data/governance-health-fresh.txt");
    screwm_governance_follow_active = screwm_read_norm("data/governance-follow-active.txt");
    screwm_governance_follow_confidence = screwm_read_norm("data/governance-follow-confidence.txt");
    screwm_governance_follow_fresh = screwm_read_norm("data/governance-follow-fresh.txt");
};

void() screwm_apply_review_camera =
{
    float phase;
    float cycle;
    float u;
    float s;
    float manual;
    float fov;
    float native_delta;
    float native_move;
    float native_hold;
    float native_speed;
    float active_period;
    vector angle_delta;
    vector origin_a;
    vector origin_b;
    vector target;
    vector target_a;
    vector target_b;

    if (cvar("screwm_csqc_review_camera") <= 0)
        return;

    if (!screwm_native_angles_ready)
    {
        screwm_native_last_angles = input_angles;
        screwm_native_angles_ready = TRUE;
    }

    angle_delta = input_angles - screwm_native_last_angles;
    native_delta = screwm_abs(angle_delta_x) + screwm_abs(angle_delta_y);
    native_move = screwm_abs(input_movevalues_x) + screwm_abs(input_movevalues_y) + screwm_abs(input_movevalues_z);
    if (cvar("screwm_csqc_native_controller") > 0 && (native_delta > 0.01 || native_move > 1 || input_buttons > 0))
    {
        native_hold = cvar("screwm_csqc_native_hold_s");
        if (native_hold <= 0)
            native_hold = 20;
        screwm_review_camera_manual_until = time + native_hold;
    }

    manual = screwm_read_norm("data/camera-manual.txt");
    if (cvar("screwm_csqc_native_controller") > 0 && screwm_review_camera_manual_until > time)
    {
        screwm_review_camera_angles_x = screwm_clamp(screwm_review_camera_angles_x + angle_delta_x, -72, 72);
        screwm_review_camera_angles_y = screwm_review_camera_angles_y + angle_delta_y;
        screwm_review_camera_angles_z = 0;

        native_speed = cvar("screwm_csqc_native_speed");
        if (native_speed <= 0)
            native_speed = 1.0;
        makevectors(screwm_review_camera_angles);
        screwm_review_camera_origin = screwm_review_camera_origin + v_forward * input_movevalues_x * frametime * native_speed;
        screwm_review_camera_origin = screwm_review_camera_origin + v_right * input_movevalues_y * frametime * native_speed;
        screwm_review_camera_origin_z = screwm_review_camera_origin_z + input_movevalues_z * frametime * native_speed;
        screwm_review_camera_origin_x = screwm_clamp(screwm_review_camera_origin_x, -1900, 1900);
        screwm_review_camera_origin_y = screwm_clamp(screwm_review_camera_origin_y, -2440, 1180);
        screwm_review_camera_origin_z = screwm_clamp(screwm_review_camera_origin_z, -48, 1710);
    }
    else if (cvar("screwm_csqc_manual_camera") > 0 && manual > 0)
    {
        screwm_review_camera_origin_x = screwm_read_float("data/camera-origin-x.txt", screwm_review_camera_origin_x);
        screwm_review_camera_origin_y = screwm_read_float("data/camera-origin-y.txt", screwm_review_camera_origin_y);
        screwm_review_camera_origin_z = screwm_read_float("data/camera-origin-z.txt", screwm_review_camera_origin_z);
        screwm_review_camera_angles_x = screwm_read_float("data/camera-pitch.txt", screwm_review_camera_angles_x);
        screwm_review_camera_angles_y = screwm_read_float("data/camera-yaw.txt", screwm_review_camera_angles_y);
        screwm_review_camera_angles_z = 0;
        fov = screwm_read_float("data/camera-fov.txt", 70);
        screwm_review_camera_fov_x = fov;
        screwm_review_camera_fov_y = fov * 0.625;
    }
    else if (cvar("screwm_csqc_review_path") > 0)
    {
        active_period = screwm_read_float("data/camera-period.txt", screwm_review_camera_period);
        active_period = screwm_clamp(active_period, 24, 720);
        cycle = time * 800 / active_period;
        while (cycle >= 800)
            cycle = cycle - 800;

        // Eight-station roji walk: broad loop, deliberate reveal/conceal, and
        // no roll/spin. The opening segment holds the AoA centered so OBS
        // feedback starts from an oriented, critiqueable room view.
        if (cycle < 100)
        {
            u = cycle / 100;
            origin_a = '0 -2360 190';
            origin_b = '-240 -2200 204';
            target_a = '0 -555 254';
            target_b = '0 -555 258';
        }
        else if (cycle < 200)
        {
            u = (cycle - 100) / 100;
            origin_a = '-240 -2200 204';
            origin_b = '-560 -1880 218';
            target_a = '0 -555 258';
            target_b = '0 -555 262';
        }
        else if (cycle < 300)
        {
            u = (cycle - 200) / 100;
            origin_a = '-560 -1880 218';
            origin_b = '-720 -1460 230';
            target_a = '0 -555 262';
            target_b = '0 -555 262';
        }
        else if (cycle < 400)
        {
            u = (cycle - 300) / 100;
            origin_a = '-720 -1460 230';
            origin_b = '-520 -1120 224';
            target_a = '0 -555 262';
            target_b = '0 -555 262';
        }
        else if (cycle < 500)
        {
            u = (cycle - 400) / 100;
            origin_a = '-520 -1120 224';
            origin_b = '520 -1120 224';
            target_a = '0 -555 262';
            target_b = '0 -555 262';
        }
        else if (cycle < 600)
        {
            u = (cycle - 500) / 100;
            origin_a = '520 -1120 224';
            origin_b = '720 -1460 230';
            target_a = '0 -555 262';
            target_b = '0 -555 262';
        }
        else if (cycle < 700)
        {
            u = (cycle - 600) / 100;
            origin_a = '720 -1460 230';
            origin_b = '560 -1880 218';
            target_a = '0 -555 262';
            target_b = '0 -555 262';
        }
        else
        {
            u = (cycle - 700) / 100;
            origin_a = '560 -1880 218';
            origin_b = '0 -2360 190';
            target_a = '0 -555 262';
            target_b = '0 -555 254';
        }

        s = u * u * (3 - 2 * u);
        phase = time * screwm_review_camera_two_pi / active_period;
        screwm_review_camera_origin = origin_a + (origin_b - origin_a) * s;
        screwm_review_camera_origin_z = screwm_review_camera_origin_z + sin(phase * 2) * 3;

        target = target_a + (target_b - target_a) * s;
        target_z = target_z + sin(phase * 1.5 + 0.4) * 4;
        screwm_review_camera_angles = vectoangles(target - screwm_review_camera_origin);
        screwm_review_camera_angles_z = 0;
        screwm_review_camera_fov = '92 57.5 0';
    }
    screwm_native_last_angles = input_angles;

    setproperty(VF_ORIGIN, screwm_review_camera_origin);
    setproperty(VF_ANGLES, screwm_review_camera_angles);
    setproperty(VF_CL_VIEWANGLES, screwm_review_camera_angles);
    setproperty(VF_FOV, screwm_review_camera_fov);
};

float(vector screen) screwm_on_screen =
{
    if (screen_x < -80)
        return FALSE;
    if (screen_x > screwm_width + 80)
        return FALSE;
    if (screen_y < -60)
        return FALSE;
    if (screen_y > screwm_height + 60)
        return FALSE;
    return TRUE;
};

void(vector a, vector b, float phase, vector color) screwm_draw_link =
{
    vector pa;
    vector pb;
    float alpha;

    pa = cs_project(a);
    pb = cs_project(b);
    pa_z = 0;
    pb_z = 0;
    if (!screwm_on_screen(pa))
        return;
    if (!screwm_on_screen(pb))
        return;

    alpha = 0.18 + 0.11 * sin(time * 1.2 + phase);
    if (screwm_voice > 0)
        alpha = alpha + 0.08;
    drawline(1.4, pa, pb, color, screwm_clamp(alpha, 0.08, 0.38), DRAWFLAG_ADDITIVE);
};

void(vector org, string ordinal, string label, float idx, vector color) screwm_draw_ward_label =
{
    vector p;
    vector code_pos;
    vector label_pos;
    float alpha;

    p = cs_project(org);
    p_z = 0;
    if (!screwm_on_screen(p))
        return;

    alpha = 0.62 + 0.18 * sin(time * 1.7 + idx * 0.43);
    if (screwm_voice > 0)
        alpha = alpha + 0.12;
    alpha = screwm_clamp(alpha, 0.42, 0.92);

    code_pos = p + '-16 -8 0';
    label_pos = p + '8 -6 0';
    drawstring(code_pos, ordinal, '7 7 0', color, alpha, DRAWFLAG_ADDITIVE);
    drawstring(label_pos, label, '5 5 0', color, alpha * 0.82, DRAWFLAG_ADDITIVE);
};

void(vector org, string text, float idx, vector color) screwm_draw_ward_detail =
{
    vector p;
    float alpha;

    if (!text)
        return;

    p = cs_project(org);
    p_z = 0;
    if (!screwm_on_screen(p))
        return;

    alpha = 0.42 + 0.16 * sin(time * 1.1 + idx * 0.31);
    drawstring(p + '-31 10 0', text, '4 4 0', color, screwm_clamp(alpha, 0.26, 0.68), DRAWFLAG_ADDITIVE);
};

float() screwm_diagnostic_lightfield_enabled =
{
    return cvar("screwm_csqc_diagnostic_lightfield") > 0;
};

float() screwm_effect_lightfield_enabled =
{
    return cvar("screwm_csqc_effect_lightfield") > 0 || screwm_diagnostic_lightfield_enabled();
};

float() screwm_roaming_surface_pulses_enabled =
{
    return cvar("screwm_csqc_roaming_surface_pulses") > 0 || screwm_diagnostic_lightfield_enabled();
};

float() screwm_surface_grid_overlay_enabled =
{
    return cvar("screwm_csqc_surface_grid_overlay") > 0 || screwm_diagnostic_lightfield_enabled();
};

float() screwm_shadow_budget_enabled =
{
    return cvar("screwm_csqc_shadow_budget") > 0;
};

float() screwm_effect_expression_pressure =
{
    float pressure;

    pressure = 0.10;
    pressure = pressure + screwm_effect_drift_active_ratio * 0.34;
    pressure = pressure + screwm_effect_drift_active_effect_ratio * 0.24;
    pressure = pressure + screwm_effect_drift_kind_variance * 0.26;
    pressure = pressure + screwm_effect_drift_max_delta * 0.22;
    pressure = pressure + screwm_effect_drift_density_currency * 0.32;
    pressure = pressure + screwm_chain_param_pressure * 0.16;
    return screwm_clamp(pressure, 0, 1.40);
};

float() screwm_local_effect_pressure =
{
    float pressure;

    pressure = screwm_effect_01;
    pressure = screwm_max2(pressure, screwm_effect_02);
    pressure = screwm_max2(pressure, screwm_effect_03);
    pressure = screwm_max2(pressure, screwm_effect_04);
    pressure = screwm_max2(pressure, screwm_effect_05);
    pressure = screwm_max2(pressure, screwm_effect_06);
    pressure = screwm_max2(pressure, screwm_effect_07);
    pressure = screwm_max2(pressure, screwm_effect_08);
    pressure = screwm_max2(pressure, screwm_effect_09);
    pressure = screwm_max2(pressure, screwm_effect_10);
    pressure = screwm_max2(pressure, screwm_effect_11);
    return pressure;
};

void(vector org, float idx, vector color, float active, float presence) screwm_add_ward_light =
{
    float radius;
    float activity;
    float homage_boost;
    float gate;

    if (!screwm_effect_lightfield_enabled())
        return;

    activity = screwm_clamp(active + presence * 0.70, 0, 1);

    // Drift-gated lightfield (operator 2026-05-29: drift should interact with the
    // lighting, w/ shadows). A ward emits light only when its OWN drift signal is
    // live, so the lit — and therefore shadow-casting — set stays small and moves
    // spatially through the room as drift moves; it is never all 36 at once (which
    // both reads as a global pulse and blows the shadowed-dlight 1080p60 budget).
    // Tunable live via screwm_ward_light_gate so the shadow budget dials without a
    // rebuild. The scroom geometry + emissive live-textures carry the room at idle;
    // ward dlights are the drift-driven accent pools on top.
    gate = cvar("screwm_ward_light_gate");
    if (gate <= 0)
        gate = 0.10;
    if (activity < gate)
        return;

    radius = 34 + screwm_energy * 24 + screwm_voice * 38 + active * 118;
    radius = radius + presence * 96 + activity * 34;
    radius = radius + screwm_audio_rms * 16 + screwm_audio_onset * 26;
    homage_boost = screwm_homage_quake * (10 + screwm_homage_transition * 34 + screwm_homage_signature * 26);
    radius = radius + homage_boost;
    adddynamiclight(org, screwm_clamp(radius, 28, 158), color);
    adddynamiclight(org + '0 0 18', screwm_clamp(radius * 0.42, 12, 78), color);
};

void() screwm_add_ward_property_field_lights =
{
    float depth_radius;
    float glow_radius;
    float front_radius;
    float drift_radius;
    float presence_radius;

    if (!screwm_effect_lightfield_enabled())
        return;

    depth_radius = 18 + screwm_ward_property_depth_pressure * 82;
    depth_radius = depth_radius + screwm_ward_property_fishbowl_pressure * 34;
    adddynamiclight('0 -404 290', screwm_clamp(depth_radius, 10, 142), screwm_cyan);

    glow_radius = 14 + screwm_ward_property_glow_pressure * 104;
    glow_radius = glow_radius + screwm_ward_property_active_ratio * 36;
    adddynamiclight('-260 -404 248', screwm_clamp(glow_radius, 8, 138), screwm_amber);

    front_radius = 14 + screwm_ward_property_front_pressure * 98;
    front_radius = front_radius + screwm_ward_property_presence_pressure * 34;
    adddynamiclight('260 -404 248', screwm_clamp(front_radius, 8, 138), screwm_green);

    drift_radius = 12 + screwm_ward_property_drift_pressure * 106;
    drift_radius = drift_radius + screwm_audio_rms * 16;
    adddynamiclight('0 -404 116', screwm_clamp(drift_radius, 8, 142), screwm_rose);

    presence_radius = 12 + screwm_ward_property_presence_pressure * 92;
    presence_radius = presence_radius + screwm_ward_property_active_ratio * 76;
    adddynamiclight('0 -430 356', screwm_clamp(presence_radius, 8, 150), screwm_amber);
};

void(vector org, float idx, vector color, float priority, float fresh) screwm_add_source_light =
{
    float radius;

    radius = 16 + priority * 36 + fresh * 84;
    radius = radius + screwm_audio_rms * 8 + screwm_audio_onset * 14;
    adddynamiclight(org, screwm_clamp(radius, 12, 118), color);
};

void(vector org, float idx, vector color, float signal) screwm_add_aoa_pane_light =
{
    float radius;

    if (!screwm_effect_lightfield_enabled())
        return;

    radius = 16 + screwm_energy * 22 + signal * 92;
    radius = radius + screwm_audio_onset * 18 + screwm_homage_quake * (8 + screwm_homage_transition * 20);
    adddynamiclight(org, screwm_clamp(radius, 10, 120), color);
};

void(vector org, float idx, vector color, float signal, float fresh) screwm_add_scene_graph_light =
{
    float radius;

    if (!screwm_diagnostic_lightfield_enabled())
        return;

    radius = 14 + screwm_energy * 18 + signal * 64 + fresh * 52;
    radius = radius + screwm_audio_rms * 10 + screwm_homage_quake * (6 + screwm_homage_signature * 18);
    adddynamiclight(org, screwm_clamp(radius, 10, 104), color);
};

void(vector org, float idx, vector color, float fresh, float opacity, float area) screwm_add_content_source_light =
{
    float radius;

    radius = 10 + fresh * 78 + opacity * 46 + area * 42;
    radius = radius + screwm_content_source_count * 16 + screwm_audio_rms * 8;
    adddynamiclight(org, screwm_clamp(radius, 8, 142), color);
};

void() screwm_add_media_source_signal_lights =
{
    screwm_add_source_light('-1580 -2140 290', 1, screwm_amber, screwm_source_priority_01, screwm_source_fresh_01);
    screwm_add_source_light('-1580 -1320 190', 2, screwm_green, screwm_source_priority_02, screwm_source_fresh_02);
    screwm_add_source_light('-1580 -500 300', 3, screwm_rose, screwm_source_priority_03, screwm_source_fresh_03);
    screwm_add_source_light('1580 -2140 290', 4, screwm_cyan, screwm_source_priority_04, screwm_source_fresh_04);
    screwm_add_source_light('1580 -1320 190', 5, screwm_green, screwm_source_priority_05, screwm_source_fresh_05);
    screwm_add_source_light('1580 -500 300', 6, screwm_green, screwm_source_priority_06, screwm_source_fresh_06);
    screwm_add_content_source_light('-1580 -2140 290', 1, screwm_cyan, screwm_content_fresh_01, screwm_content_opacity_01, screwm_content_area_01);
    screwm_add_content_source_light('-1580 -1320 190', 2, screwm_green, screwm_content_fresh_02, screwm_content_opacity_02, screwm_content_area_02);
    screwm_add_content_source_light('-1580 -500 300', 3, screwm_rose, screwm_content_fresh_03, screwm_content_opacity_03, screwm_content_area_03);
    screwm_add_content_source_light('1580 -2140 290', 4, screwm_amber, screwm_content_fresh_04, screwm_content_opacity_04, screwm_content_area_04);
    screwm_add_content_source_light('1580 -1320 190', 5, screwm_cyan, screwm_content_fresh_05, screwm_content_opacity_05, screwm_content_area_05);
    screwm_add_content_source_light('1580 -500 300', 6, screwm_green, screwm_content_fresh_06, screwm_content_opacity_06, screwm_content_area_06);
};

void() screwm_add_aoa_pane_signal_lights =
{
    screwm_add_aoa_pane_light('-4 -597 332', 1, screwm_cyan, screwm_aoa_pane_01);
    screwm_add_aoa_pane_light('-72 -597 286', 2, screwm_green, screwm_aoa_pane_02);
    screwm_add_aoa_pane_light('72 -597 286', 3, screwm_amber, screwm_aoa_pane_03);
    screwm_add_aoa_pane_light('-118 -597 218', 4, screwm_rose, screwm_aoa_pane_04);
    screwm_add_aoa_pane_light('118 -597 218', 5, screwm_cyan, screwm_aoa_pane_05);
    screwm_add_aoa_pane_light('-76 -597 150', 6, screwm_green, screwm_aoa_pane_06);
    screwm_add_aoa_pane_light('76 -597 150', 7, screwm_amber, screwm_aoa_pane_07);
    screwm_add_aoa_pane_light('-176 -597 264', 8, screwm_rose, screwm_aoa_pane_08);
    screwm_add_aoa_pane_light('176 -597 264', 9, screwm_cyan, screwm_aoa_pane_09);
    screwm_add_aoa_pane_light('0 -597 112', 10, screwm_green, screwm_aoa_pane_10);
};

void(vector org, float idx, vector color, float signal) screwm_add_local_effect_light =
{
    float radius;
    float expression;
    float phase;
    vector lift;

    if (!screwm_effect_lightfield_enabled())
        return;

    expression = screwm_effect_expression_pressure();
    phase = time * (0.041 + idx * 0.003) + idx * 0.77 + screwm_effect_drift_kind_variance * 2.2;
    lift = '0 0 0';
    lift_x = sin(phase) * (16 + screwm_effect_drift_fast_ratio * 36);
    lift_y = cos(phase * 0.73) * (18 + screwm_effect_drift_slow_ratio * 42);
    lift_z = sin(phase * 1.31) * (12 + expression * 44);

    radius = 18 + screwm_energy * 18 + signal * 126;
    radius = radius + screwm_effect_drift_active_effect_ratio * 42 + screwm_effect_drift_kind_variance * 36;
    radius = radius + screwm_effect_drift_density_currency * 72 + expression * 54;
    radius = radius + screwm_reverie_temporal * 20 + screwm_reverie_material * 24;
    radius = radius + screwm_audio_onset * 24 + screwm_homage_signature * 16;
    adddynamiclight(org + lift, screwm_clamp(radius, 16, 198), color);
    if (screwm_shadow_budget_enabled())
        return;
    adddynamiclight(org + lift * -0.45 + '0 0 52', screwm_clamp(radius * 0.42, 8, 82), color * 0.44);
};

void(vector org, float idx, vector color, float active_src, float active_dst) screwm_add_drift_light =
{
    float activity;
    float radius;
    float homage_boost;

    if (!screwm_effect_lightfield_enabled())
        return;

    activity = screwm_clamp(active_src + active_dst, 0, 1);
    radius = 18 + screwm_energy * 20 + activity * 58;
    radius = radius + screwm_audio_rms * 18 + screwm_audio_onset * 34;
    radius = radius + screwm_effect_drift_active_ratio * 30 + screwm_chain_drift * 22;
    radius = radius + screwm_effect_drift_active_slot_ratio * 18 + screwm_effect_drift_kind_variance * 20;
    radius = radius + screwm_effect_drift_fast_ratio * 14 + screwm_effect_drift_slow_ratio * 10;
    homage_boost = screwm_homage_quake * (10 + screwm_homage_transition * 26);
    radius = radius + homage_boost;
    adddynamiclight(org, screwm_clamp(radius, 12, 94), color);
};

void() screwm_add_homage_lights =
{
    float field;

    if (screwm_homage_quake <= 0)
        return;

    field = 48 + screwm_homage_transition * 80 + screwm_homage_signature * 56;
    field = field + screwm_energy * 24;
    adddynamiclight('0 -372 172', screwm_clamp(field, 36, 140), screwm_cyan);
    adddynamiclight('-148 -360 226', screwm_clamp(field * 0.55, 24, 88), screwm_amber);
    adddynamiclight('148 -360 118', screwm_clamp(field * 0.55, 24, 88), screwm_green);
};

void() screwm_add_material_field_lights =
{
    float material_field;
    float spectral_field;
    float temporal_field;
    float thermal_field;
    float room_field;
    float floor_field;
    float wall_field;
    float ceiling_field;

    if (cvar("screwm_csqc_material_field") <= 0)
        return;

    material_field = screwm_reverie_material + screwm_audio_rms * 0.55 + screwm_homage_signature * 0.35;
    spectral_field = screwm_reverie_spectral + screwm_audio_onset * 0.40 + screwm_homage_transition * 0.30;
    temporal_field = screwm_reverie_temporal + screwm_audio_onset * 0.35;
    thermal_field = screwm_reverie_thermal + screwm_homage_quake * 0.28;
    room_field = screwm_clamp(material_field + screwm_effect_drift_active_ratio * 0.85 + screwm_chain_drift * 0.50 + screwm_effect_drift_kind_variance * 0.35, 0, 2.5);
    floor_field = screwm_clamp(temporal_field + screwm_effect_drift_edge * 0.70 + screwm_chain_aperture * 0.40 + screwm_effect_drift_fast_ratio * 0.28, 0, 2.5);
    wall_field = screwm_clamp(spectral_field + screwm_chain_color * 0.45 + screwm_chain_noise * 0.35 + screwm_effect_drift_active_effect_ratio * 0.32, 0, 2.5);
    ceiling_field = screwm_clamp(thermal_field + screwm_chain_feedback * 0.45 + screwm_chain_drift * 0.35 + screwm_effect_drift_slow_ratio * 0.28, 0, 2.5);

    adddynamiclight('0 -620 326', screwm_clamp(42 + material_field * 96, 24, 138), screwm_cyan);
    adddynamiclight('0 -588 252', screwm_clamp(26 + spectral_field * 76, 14, 106), screwm_green);
    adddynamiclight('-180 -595 300', screwm_clamp(22 + material_field * 64, 12, 92), screwm_amber);
    adddynamiclight('180 -595 260', screwm_clamp(22 + thermal_field * 72, 12, 104), screwm_rose);
    adddynamiclight('-120 -650 104', screwm_clamp(18 + temporal_field * 58, 10, 84), screwm_green);
    adddynamiclight('0 -1910 36', screwm_clamp(34 + floor_field * 88, 18, 154), screwm_cyan);
    adddynamiclight('-760 -1510 42', screwm_clamp(22 + floor_field * 66, 12, 126), screwm_green);
    adddynamiclight('760 -1210 42', screwm_clamp(22 + room_field * 62, 12, 132), screwm_rose);
    adddynamiclight('420 -430 54', screwm_clamp(20 + floor_field * 70, 10, 132), screwm_amber);
    adddynamiclight('-1170 -1320 230', screwm_clamp(18 + wall_field * 74, 10, 138), screwm_cyan);
    adddynamiclight('1170 -1320 230', screwm_clamp(18 + wall_field * 74, 10, 138), screwm_rose);
    adddynamiclight('0 -1320 504', screwm_clamp(18 + ceiling_field * 84, 10, 146), screwm_cyan);
    adddynamiclight('0 -430 512', screwm_clamp(16 + ceiling_field * 72, 8, 132), screwm_green);
};

void(vector org, float idx, vector color, float signal) screwm_add_visual_zone_light =
{
    float radius;

    radius = 12 + signal * 84 + screwm_visual_display * 28;
    radius = radius + screwm_visual_turbulence * 18 + screwm_audio_onset * 12;
    adddynamiclight(org, screwm_clamp(radius, 8, 118), color);
};

void() screwm_add_visual_layer_lights =
{
    float stance_radius;
    float fault_radius;

    if (!screwm_effect_lightfield_enabled())
        return;

    screwm_add_visual_zone_light('-300 -548 340', 1, screwm_amber, screwm_visual_zone_01);
    screwm_add_visual_zone_light('-214 -548 340', 2, screwm_rose, screwm_visual_zone_02);
    screwm_add_visual_zone_light('-128 -548 340', 3, screwm_cyan, screwm_visual_zone_03);
    screwm_add_visual_zone_light('-42 -548 340', 4, screwm_green, screwm_visual_zone_04);
    screwm_add_visual_zone_light('42 -548 340', 5, screwm_green, screwm_visual_zone_05);
    screwm_add_visual_zone_light('128 -548 340', 6, screwm_amber, screwm_visual_zone_06);
    screwm_add_visual_zone_light('214 -548 340', 7, screwm_cyan, screwm_visual_zone_07);
    screwm_add_visual_zone_light('300 -548 340', 8, screwm_cyan, screwm_visual_zone_08);

    stance_radius = 28 + screwm_visual_stance * 90 + screwm_stimmung_operator_energy * 22;
    stance_radius = stance_radius + screwm_visual_brightness * 24;
    adddynamiclight('0 -520 382', screwm_clamp(stance_radius, 18, 138), screwm_cyan);

    fault_radius = 18 + screwm_stimmung_health * 44 + screwm_stimmung_resource * 50;
    fault_radius = fault_radius + screwm_stimmung_error * 86 + screwm_visual_display * 30;
    adddynamiclight('-306 -506 300', screwm_clamp(fault_radius, 12, 152), screwm_rose);
    adddynamiclight('306 -506 300', screwm_clamp(22 + screwm_stimmung_audience * 94, 12, 130), screwm_green);
};

void(vector org, float idx, vector color, float signal) screwm_add_visual_chain_light =
{
    float radius;

    radius = 10 + signal * 96 + screwm_chain_param_pressure * 24;
    radius = radius + screwm_effect_drift_active_ratio * 22 + screwm_effect_drift_kind_variance * 20;
    radius = radius + screwm_audio_rms * 10;
    adddynamiclight(org, screwm_clamp(radius, 8, 136), color);
};

void() screwm_add_visual_chain_lights =
{
    float param_radius;
    float drift_radius;

    if (!screwm_effect_lightfield_enabled())
        return;

    screwm_add_visual_chain_light('-300 -526 74', 1, screwm_amber, screwm_chain_01);
    screwm_add_visual_chain_light('-225 -526 74', 2, screwm_rose, screwm_chain_02);
    screwm_add_visual_chain_light('-150 -526 74', 3, screwm_cyan, screwm_chain_03);
    screwm_add_visual_chain_light('-75 -526 74', 4, screwm_green, screwm_chain_04);
    screwm_add_visual_chain_light('0 -526 74', 5, screwm_amber, screwm_chain_05);
    screwm_add_visual_chain_light('75 -526 74', 6, screwm_rose, screwm_chain_06);
    screwm_add_visual_chain_light('150 -526 74', 7, screwm_green, screwm_chain_07);
    screwm_add_visual_chain_light('225 -526 74', 8, screwm_cyan, screwm_chain_08);
    screwm_add_visual_chain_light('300 -526 74', 9, screwm_amber, screwm_chain_09);

    param_radius = 18 + screwm_chain_param_pressure * 104 + screwm_effect_drift_max_delta * 56;
    adddynamiclight('-314 -512 128', screwm_clamp(param_radius, 12, 152), screwm_cyan);
    adddynamiclight('-156 -512 128', screwm_clamp(18 + screwm_chain_noise * 92 + screwm_effect_drift_texture * 42, 12, 138), screwm_green);
    adddynamiclight('0 -512 128', screwm_clamp(18 + screwm_chain_color * 92 + screwm_effect_drift_tonal * 48, 12, 148), screwm_rose);
    adddynamiclight('156 -512 128', screwm_clamp(18 + screwm_chain_feedback * 92 + screwm_effect_drift_temporal * 48, 12, 148), screwm_amber);
    drift_radius = 18 + screwm_chain_drift * 104 + screwm_effect_drift_atmospheric * 56;
    drift_radius = drift_radius + screwm_effect_drift_region_count * 34;
    adddynamiclight('314 -512 128', screwm_clamp(drift_radius, 12, 156), screwm_cyan);
    adddynamiclight('314 -512 42', screwm_clamp(14 + screwm_effect_drift_compositing * 104 + screwm_chain_feedback * 24, 10, 142), screwm_rose);
    adddynamiclight('0 -512 42', screwm_clamp(14 + screwm_chain_aperture * 84 + screwm_effect_drift_edge * 52, 10, 132), screwm_green);
};

float(float target) screwm_imagination_material_weight =
{
    return screwm_clamp(1 - screwm_abs(screwm_imagination_material - target) * 4, 0, 1);
};

void(vector org, float idx, vector color, float signal) screwm_add_imagination_dim_light =
{
    float radius;

    radius = 12 + signal * 90 + screwm_imagination_salience * 42;
    radius = radius + screwm_imagination_continuation * 18 + screwm_audio_onset * 12;
    adddynamiclight(org, screwm_clamp(radius, 8, 144), color);
};

void() screwm_add_imagination_intent_lights =
{
    float core;

    core = 24 + screwm_imagination_salience * 118 + screwm_imagination_continuation * 34;
    adddynamiclight('0 -597 178', screwm_clamp(core, 18, 170), screwm_amber);
    adddynamiclight('-54 -596 216', screwm_clamp(18 + screwm_imagination_material_weight(0.00) * 112, 10, 138), screwm_cyan);
    adddynamiclight('54 -596 216', screwm_clamp(18 + screwm_imagination_material_weight(0.25) * 112, 10, 138), screwm_rose);
    adddynamiclight('-54 -596 140', screwm_clamp(18 + screwm_imagination_material_weight(0.50) * 112, 10, 138), screwm_green);
    adddynamiclight('54 -596 140', screwm_clamp(18 + screwm_imagination_material_weight(0.75) * 112, 10, 138), screwm_cyan);
    adddynamiclight('0 -596 104', screwm_clamp(12 + screwm_imagination_material_weight(1.00) * 96, 8, 118), screwm_dim);

    screwm_add_imagination_dim_light('-132 -602 284', 1, screwm_amber, screwm_imagination_dim_01);
    screwm_add_imagination_dim_light('0 -602 304', 2, screwm_rose, screwm_imagination_dim_02);
    screwm_add_imagination_dim_light('132 -602 284', 3, screwm_cyan, screwm_imagination_dim_03);
    screwm_add_imagination_dim_light('-150 -602 206', 4, screwm_green, screwm_imagination_dim_04);
    screwm_add_imagination_dim_light('150 -602 206', 5, screwm_rose, screwm_imagination_dim_05);
    screwm_add_imagination_dim_light('-132 -602 122', 6, screwm_cyan, screwm_imagination_dim_06);
    screwm_add_imagination_dim_light('0 -602 92', 7, screwm_amber, screwm_imagination_dim_07);
    screwm_add_imagination_dim_light('132 -602 122', 8, screwm_green, screwm_imagination_dim_08);
    screwm_add_imagination_dim_light('0 -602 238', 9, screwm_rose, screwm_imagination_dim_09);
};

void() screwm_add_local_effect_lights =
{
    if (!screwm_effect_lightfield_enabled())
        return;

    screwm_add_local_effect_light('-980 -1780 214', 1, screwm_cyan, screwm_effect_01);
    screwm_add_local_effect_light('0 -1320 512', 2, screwm_rose, screwm_effect_02);
    screwm_add_local_effect_light('-520 -860 96', 3, screwm_green, screwm_effect_03);
    screwm_add_local_effect_light('520 -860 238', 4, screwm_cyan, screwm_effect_04);
    screwm_add_local_effect_light('-1040 -280 342', 5, screwm_amber, screwm_effect_05);
    screwm_add_local_effect_light('1040 -1420 64', 6, screwm_rose, screwm_effect_06);
    screwm_add_local_effect_light('0 -2140 316', 7, screwm_cyan, screwm_effect_07);
    screwm_add_local_effect_light('0 -2360 98', 8, screwm_green, screwm_effect_08);
    screwm_add_local_effect_light('-760 720 386', 9, screwm_amber, screwm_effect_09);
    screwm_add_local_effect_light('0 -590 220', 10, screwm_green, screwm_effect_10);
    screwm_add_local_effect_light('760 720 148', 11, screwm_amber, screwm_effect_11);
};

void(vector org, float idx, vector color, float signal, vector axis) screwm_add_world_edge_light =
{
    float phase;
    float pulse;
    float radius;
    vector jitter;

    if (!screwm_effect_lightfield_enabled())
        return;

    phase = time * (0.071 + idx * 0.004 + screwm_effect_drift_fast_ratio * 0.035);
    phase = phase + idx * 0.61 + screwm_effect_drift_kind_variance * 3.4;
    pulse = 0.50 + 0.50 * sin(phase * 1.31 + screwm_effect_drift_max_delta * 2.4);
    jitter = '0 0 0';
    jitter_x = axis_x * sin(phase) * (18 + screwm_effect_drift_fast_ratio * 48 + screwm_effect_drift_edge * 28);
    jitter_y = axis_y * cos(phase * 0.79) * (18 + screwm_effect_drift_slow_ratio * 52 + screwm_effect_drift_texture * 24);
    jitter_z = axis_z * sin(phase * 1.17) * (10 + screwm_effect_drift_edge * 62 + screwm_effect_drift_temporal * 22);

    radius = 64 + signal * 96 + screwm_effect_drift_edge * 118 + screwm_effect_mode_edge * 42;
    radius = radius + screwm_effect_drift_texture * 64 + screwm_effect_drift_active_ratio * 74;
    radius = radius + screwm_effect_drift_kind_variance * 54 + screwm_chain_aperture * 34;
    radius = radius + pulse * (86 + signal * 78 + screwm_effect_drift_fast_ratio * 52);
    radius = radius + screwm_audio_onset * 34 + screwm_audio_rms * 22;
    adddynamiclight(org + jitter, screwm_clamp(radius, 42, 820), color);
};

void() screwm_add_world_edge_lattice_lights =
{
    float pressure;
    float local_pressure;
    float edge_pressure;
    float floor_edge;
    float wall_edge;
    float ceiling_edge;
    float void_edge;
    vector roam_a;
    vector roam_b;

    if (cvar("screwm_csqc_full_expression_field") <= 0)
        return;
    if (!screwm_effect_lightfield_enabled())
        return;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();
    edge_pressure = screwm_clamp(
        0.38 + pressure + local_pressure * 0.75 + screwm_effect_drift_edge * 1.20 + screwm_effect_mode_edge * 0.70 + screwm_effect_drift_texture * 0.58 + screwm_effect_drift_active_ratio * 0.68,
        0.32,
        3.4
    );

    floor_edge = screwm_clamp(edge_pressure + screwm_effect_drift_fast_ratio * 0.36 + screwm_effect_drift_active_effect_ratio * 0.22, 0, 2.7);
    wall_edge = screwm_clamp(edge_pressure + screwm_effect_drift_texture * 0.40 + screwm_effect_drift_compositing * 0.28, 0, 2.7);
    ceiling_edge = screwm_clamp(edge_pressure + screwm_effect_drift_slow_ratio * 0.44 + screwm_effect_drift_temporal * 0.30, 0, 2.7);
    void_edge = screwm_clamp(edge_pressure + screwm_effect_drift_density_currency * 0.55 + screwm_effect_drift_atmospheric * 0.36, 0, 2.7);
    roam_a = screwm_synthwave_color(time * 0.049 + screwm_effect_drift_region_count * 3.2);
    roam_b = screwm_synthwave_color(time * 0.037 + screwm_effect_drift_kind_variance * 5.7 + 1.8);

    screwm_add_world_edge_light('0 -2230 42', 1, screwm_amber, floor_edge, '1 1 0.20');
    screwm_add_world_edge_light('-1620 -2450 58', 2, screwm_cyan, floor_edge, '0.35 1 0.22');
    screwm_add_world_edge_light('1620 -2450 58', 3, screwm_rose, floor_edge, '0.35 1 0.22');
    screwm_add_world_edge_light('-1988 -1780 92', 4, screwm_green, floor_edge, '0.10 1 0.32');
    screwm_add_world_edge_light('1988 -1780 92', 5, screwm_cyan, floor_edge, '0.10 1 0.32');
    screwm_add_world_edge_light('0 -2070 1710', 6, screwm_cyan, ceiling_edge, '1 1 0.22');
    screwm_add_world_edge_light('-1560 -2220 1710', 7, screwm_rose, ceiling_edge, '0.28 1 0.24');
    screwm_add_world_edge_light('1560 -2220 1710', 8, screwm_green, ceiling_edge, '0.28 1 0.24');
    screwm_add_world_edge_light('-1988 -1480 1710', 9, screwm_amber, ceiling_edge, '0.08 1 0.34');
    screwm_add_world_edge_light('1988 -1480 1710', 10, screwm_cyan, ceiling_edge, '0.08 1 0.34');
    screwm_add_world_edge_light('-1990 -760 420', 11, roam_a, wall_edge, '0.06 1 1');
    screwm_add_world_edge_light('1990 -760 420', 12, roam_b, wall_edge, '0.06 1 1');
    screwm_add_world_edge_light('0 -2520 420', 13, screwm_rose, wall_edge, '1 0.08 1');
    screwm_add_world_edge_light('0 1330 420', 14, screwm_green, wall_edge, '1 0.08 1');
    screwm_add_world_edge_light('-1420 1330 1710', 15, screwm_cyan, ceiling_edge, '1 0.10 0.28');
    screwm_add_world_edge_light('1420 1330 92', 16, screwm_amber, floor_edge, '1 0.10 0.28');
    screwm_add_world_edge_light('-760 -590 124', 17, roam_a, void_edge, '0.48 0.64 0.40');
    screwm_add_world_edge_light('760 -590 124', 18, roam_b, void_edge, '0.48 0.64 0.40');
    screwm_add_world_edge_light('0 -590 446', 19, screwm_cyan, ceiling_edge, '0.74 0.34 0.28');
    screwm_add_world_edge_light('0 -590 70', 20, screwm_amber, floor_edge, '0.74 0.34 0.28');
    screwm_add_world_edge_light('-1100 580 330', 21, screwm_rose, void_edge, '0.64 0.42 0.88');
    screwm_add_world_edge_light('1100 580 330', 22, screwm_green, void_edge, '0.64 0.42 0.88');
};

void() screwm_add_entry_substrate_drift_lights =
{
    float pressure;
    float local_pressure;
    float substrate_signal;
    float phase;
    float floor_pulse;
    float ceiling_pulse;
    float core_pulse;
    float void_pulse;
    vector floor_sweep;
    vector ceiling_sweep;
    vector core_sweep;
    vector void_sweep;
    vector right_wall_sweep;
    vector roam_a;
    vector roam_b;

    if (cvar("screwm_csqc_full_expression_field") <= 0)
        return;
    if (!screwm_effect_lightfield_enabled())
        return;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();
    if (
        screwm_effect_drift_active_ratio <= 0.01
        && screwm_effect_drift_active_effect_ratio <= 0.01
        && screwm_effect_drift_edge <= 0.01
        && local_pressure <= 0.01
    )
        return;

    substrate_signal = screwm_clamp(
        pressure * 0.78 + local_pressure * 0.60 + screwm_effect_drift_active_ratio * 0.86 + screwm_effect_drift_active_effect_ratio * 0.56 + screwm_effect_drift_edge * 0.82 + screwm_effect_drift_texture * 0.48 + screwm_effect_drift_temporal * 0.42,
        0,
        2.8
    );
    if (substrate_signal <= 0.04)
        return;

    phase = time * (0.91 + screwm_effect_drift_fast_ratio * 0.29) + screwm_effect_drift_kind_variance * 5.1 + screwm_effect_drift_max_delta * 2.6;
    floor_pulse = 0.50 + 0.50 * sin(phase);
    ceiling_pulse = 0.50 + 0.50 * cos(phase * 0.81 + screwm_effect_drift_slow_ratio * 2.7);
    core_pulse = 0.50 + 0.50 * sin(phase * 1.17 + screwm_effect_drift_compositing * 3.1);
    void_pulse = 0.50 + 0.50 * cos(phase * 0.69 + screwm_effect_drift_density_currency * 4.2);
    floor_sweep = '0 -2240 36';
    floor_sweep_x = floor_sweep_x + sin(phase * 1.23) * 720;
    floor_sweep_y = floor_sweep_y + cos(phase * 0.73) * 148;
    ceiling_sweep = '0 -2160 1724';
    ceiling_sweep_x = ceiling_sweep_x + cos(phase * 0.97) * 760;
    ceiling_sweep_y = ceiling_sweep_y + sin(phase * 0.67) * 156;
    core_sweep = '0 -590 224';
    core_sweep_x = core_sweep_x + sin(phase * 1.31) * 112;
    core_sweep_z = core_sweep_z + cos(phase * 0.89) * 92;
    void_sweep = '-1480 -2290 702';
    void_sweep_x = void_sweep_x + sin(phase * 0.79) * 260;
    void_sweep_y = void_sweep_y + cos(phase * 1.07) * 172;
    void_sweep_z = void_sweep_z + sin(phase * 0.91) * 72;
    right_wall_sweep = '1960 -1540 420';
    right_wall_sweep_y = right_wall_sweep_y + sin(phase * 0.84) * 520;
    right_wall_sweep_z = right_wall_sweep_z + cos(phase * 1.12) * 190;
    roam_a = screwm_synthwave_color(phase + 0.6);
    roam_b = screwm_synthwave_color(phase + 2.4);

    adddynamiclight('0 -2240 34', screwm_clamp(54 + substrate_signal * 128 + floor_pulse * 248, 42, 620), screwm_amber);
    adddynamiclight('-520 -2190 52', screwm_clamp(38 + substrate_signal * 102 + (1 - floor_pulse) * 192, 32, 520), screwm_green);
    adddynamiclight('520 -2190 52', screwm_clamp(38 + substrate_signal * 102 + floor_pulse * 192, 32, 520), screwm_rose);
    adddynamiclight(floor_sweep, screwm_clamp(42 + substrate_signal * 112 + floor_pulse * 226, 34, 560), roam_a);
    adddynamiclight('-1120 -2360 44', screwm_clamp(34 + substrate_signal * 94 + void_pulse * 178, 28, 460), roam_b);
    adddynamiclight('1120 -2360 44', screwm_clamp(34 + substrate_signal * 94 + (1 - void_pulse) * 178, 28, 460), roam_a);
    adddynamiclight('0 -2140 1718', screwm_clamp(54 + substrate_signal * 126 + ceiling_pulse * 246, 42, 610), screwm_cyan);
    adddynamiclight('-560 -2080 1698', screwm_clamp(36 + substrate_signal * 96 + ceiling_pulse * 188, 30, 510), roam_a);
    adddynamiclight('560 -2080 1698', screwm_clamp(36 + substrate_signal * 96 + (1 - ceiling_pulse) * 188, 30, 510), roam_b);
    adddynamiclight(ceiling_sweep, screwm_clamp(42 + substrate_signal * 110 + ceiling_pulse * 224, 34, 550), roam_b);
    adddynamiclight('-1120 -2380 1708', screwm_clamp(34 + substrate_signal * 92 + (1 - void_pulse) * 180, 28, 470), roam_a);
    adddynamiclight('1120 -2380 1708', screwm_clamp(34 + substrate_signal * 92 + void_pulse * 180, 28, 470), roam_b);
    adddynamiclight('0 -590 224', screwm_clamp(32 + substrate_signal * 84 + core_pulse * 146, 24, 310), screwm_rose);
    adddynamiclight('0 -590 554', screwm_clamp(22 + substrate_signal * 58 + (1 - core_pulse) * 108, 18, 252), screwm_cyan);
    adddynamiclight(core_sweep, screwm_clamp(26 + substrate_signal * 68 + core_pulse * 132, 20, 292), screwm_green);
    adddynamiclight('-160 -590 250', screwm_clamp(24 + substrate_signal * 68 + (1 - core_pulse) * 138, 20, 298), roam_a);
    adddynamiclight('160 -590 250', screwm_clamp(24 + substrate_signal * 68 + core_pulse * 138, 20, 298), roam_b);
    adddynamiclight('-1480 -2290 1614', screwm_clamp(24 + substrate_signal * 62 + void_pulse * 138, 18, 294), roam_b);
    adddynamiclight('-1240 -2090 248', screwm_clamp(22 + substrate_signal * 54 + (1 - void_pulse) * 104, 16, 238), roam_a);
    adddynamiclight(void_sweep, screwm_clamp(24 + substrate_signal * 66 + void_pulse * 148, 18, 304), screwm_cyan);
    adddynamiclight(right_wall_sweep, screwm_clamp(24 + substrate_signal * 72 + (1 - void_pulse) * 146, 18, 312), screwm_rose);
};

void() screwm_add_shadow_budget_edge_lights =
{
    float pressure;
    float local_pressure;
    float signal;
    float phase;
    float pulse_a;
    float pulse_b;
    vector roam_a;
    vector roam_b;

    if (cvar("screwm_csqc_full_expression_field") <= 0)
        return;
    if (!screwm_effect_lightfield_enabled())
        return;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();
    signal = screwm_clamp(
        0.34 + pressure * 0.86 + local_pressure * 0.42 + screwm_effect_drift_edge * 0.72 + screwm_effect_drift_texture * 0.46 + screwm_effect_drift_density_currency * 0.36,
        0.24,
        2.6
    );
    phase = time * (0.58 + screwm_effect_drift_fast_ratio * 0.21) + screwm_effect_drift_kind_variance * 4.6 + screwm_effect_drift_max_delta * 2.1;
    pulse_a = 0.50 + 0.50 * sin(phase);
    pulse_b = 0.50 + 0.50 * cos(phase * 0.73 + screwm_effect_drift_temporal * 3.0);
    roam_a = screwm_synthwave_color(phase + 0.9);
    roam_b = screwm_synthwave_color(phase + 2.7);

    adddynamiclight('0 -2380 52', screwm_clamp(62 + signal * 132 + pulse_a * 230, 52, 640), roam_a);
    adddynamiclight('0 -2380 1710', screwm_clamp(62 + signal * 132 + pulse_b * 230, 52, 640), roam_b);
    adddynamiclight('-1540 -2280 430', screwm_clamp(48 + signal * 118 + pulse_b * 190, 42, 540), screwm_cyan);
    adddynamiclight('1540 -2280 430', screwm_clamp(48 + signal * 118 + pulse_a * 190, 42, 540), screwm_rose);
    adddynamiclight('920 -1020 1692', screwm_clamp(46 + signal * 112 + pulse_b * 184, 40, 520), roam_b);
    adddynamiclight('-920 -1020 1692', screwm_clamp(46 + signal * 112 + pulse_a * 184, 40, 520), roam_a);
    adddynamiclight('0 -590 671', screwm_clamp(54 + signal * 128 + pulse_b * 206, 44, 580), screwm_cyan);
    adddynamiclight('0 -590 89', screwm_clamp(52 + signal * 126 + pulse_a * 202, 44, 570), screwm_amber);
};

void() screwm_add_scroom_baseline_lights =
{
    if (!screwm_effect_lightfield_enabled())
        return;

    adddynamiclight('0 -1040 520', 260, '0.48 0.62 0.86');
    adddynamiclight('0 -590 286', 210, '0.92 0.56 0.32');
    adddynamiclight('-720 -690 352', 170, '0.38 0.86 0.94');
    adddynamiclight('720 -690 352', 170, '0.94 0.36 0.62');
    adddynamiclight('0 -1660 74', 190, '0.74 0.58 0.34');
    adddynamiclight('0 -1660 1672', 170, '0.42 0.72 0.92');
};

void() screwm_add_aoa_drift_lights =
{
    float pressure;
    float local_pressure;
    float signal;
    float phase;
    float pulse;
    vector roam_a;
    vector roam_b;

    if (!screwm_effect_lightfield_enabled())
        return;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();
    signal = screwm_clamp(
        0.36 + pressure * 0.74 + local_pressure * 0.48 + screwm_effect_drift_active_ratio * 0.48 + screwm_effect_drift_active_effect_ratio * 0.30 + screwm_effect_drift_edge * 0.42 + screwm_effect_drift_texture * 0.28,
        0.24,
        2.3
    );
    phase = time * (0.62 + screwm_effect_drift_fast_ratio * 0.24) + screwm_effect_drift_kind_variance * 4.8 + screwm_effect_drift_max_delta * 2.2;
    pulse = 0.50 + 0.50 * sin(phase);
    roam_a = screwm_synthwave_color(phase);
    roam_b = screwm_synthwave_color(phase + 2.4);

    adddynamiclight('0 -590 224', screwm_clamp(126 + signal * 154 + pulse * 118, 96, 520), roam_a);
    adddynamiclight('0 -590 419', screwm_clamp(96 + signal * 132 + (1 - pulse) * 104, 76, 440), roam_b);
    adddynamiclight('-190 -590 262', screwm_clamp(72 + signal * 98 + pulse * 82, 54, 330), screwm_cyan);
    adddynamiclight('190 -590 262', screwm_clamp(72 + signal * 98 + (1 - pulse) * 82, 54, 330), screwm_rose);
    adddynamiclight('0 -590 71', screwm_clamp(74 + signal * 92 + screwm_effect_drift_edge * 98, 52, 360), screwm_amber);
};

void() screwm_add_hex_grid_drift_lights =
{
    float pressure;
    float local_pressure;
    float grid_signal;
    float phase;
    float floor_pulse;
    float ceiling_pulse;
    vector roam_a;
    vector roam_b;

    if (cvar("screwm_csqc_full_expression_field") <= 0)
        return;
    if (!screwm_effect_lightfield_enabled())
        return;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();
    grid_signal = screwm_clamp(
        0.58 + pressure * 1.02 + local_pressure * 0.64 + screwm_effect_drift_edge * 1.04 + screwm_effect_drift_texture * 0.78 + screwm_effect_drift_fast_ratio * 0.44 + screwm_effect_drift_slow_ratio * 0.38,
        0.48,
        3.4
    );
    phase = time * (0.44 + screwm_effect_drift_fast_ratio * 0.18) + screwm_effect_drift_kind_variance * 5.3;
    floor_pulse = 0.50 + 0.50 * sin(phase);
    ceiling_pulse = 0.50 + 0.50 * cos(phase * 0.83 + screwm_effect_drift_temporal * 3.7);
    roam_a = screwm_synthwave_color(phase + screwm_effect_drift_region_count * 0.12);
    roam_b = screwm_synthwave_color(phase + 2.1);

    adddynamiclight('0 -555 42', screwm_clamp(190 + grid_signal * 208 + floor_pulse * 184, 142, 760), screwm_amber);
    adddynamiclight('-512 -555 46', screwm_clamp(132 + grid_signal * 172 + (1 - floor_pulse) * 146, 104, 620), roam_a);
    adddynamiclight('512 -555 46', screwm_clamp(132 + grid_signal * 172 + floor_pulse * 146, 104, 620), roam_b);
    adddynamiclight('0 -998 48', screwm_clamp(118 + grid_signal * 152 + screwm_effect_drift_edge * 116, 92, 560), screwm_green);
    adddynamiclight('0 -111 48', screwm_clamp(118 + grid_signal * 152 + screwm_effect_drift_texture * 116, 92, 560), screwm_cyan);
    adddynamiclight('0 -2260 54', screwm_clamp(210 + grid_signal * 230 + floor_pulse * 224, 156, 820), roam_a);
    adddynamiclight('-820 -2180 56', screwm_clamp(146 + grid_signal * 184 + (1 - floor_pulse) * 178, 116, 680), screwm_green);
    adddynamiclight('820 -2180 56', screwm_clamp(146 + grid_signal * 184 + floor_pulse * 178, 116, 680), screwm_rose);

    adddynamiclight('0 -555 1716', screwm_clamp(184 + grid_signal * 198 + ceiling_pulse * 182, 138, 740), screwm_cyan);
    adddynamiclight('-512 -555 1706', screwm_clamp(126 + grid_signal * 162 + ceiling_pulse * 140, 98, 600), roam_b);
    adddynamiclight('512 -555 1706', screwm_clamp(126 + grid_signal * 162 + (1 - ceiling_pulse) * 140, 98, 600), roam_a);
    adddynamiclight('0 -2240 1718', screwm_clamp(204 + grid_signal * 222 + ceiling_pulse * 210, 150, 800), roam_b);
    adddynamiclight('-820 -2140 1700', screwm_clamp(138 + grid_signal * 176 + ceiling_pulse * 172, 108, 650), screwm_cyan);
    adddynamiclight('820 -2140 1700', screwm_clamp(138 + grid_signal * 176 + (1 - ceiling_pulse) * 172, 108, 650), screwm_amber);
    adddynamiclight('-1980 -555 430', screwm_clamp(112 + grid_signal * 148 + screwm_effect_drift_compositing * 128, 86, 560), screwm_cyan);
    adddynamiclight('1980 -555 430', screwm_clamp(112 + grid_signal * 148 + screwm_effect_drift_atmospheric * 128, 86, 560), screwm_rose);
    adddynamiclight('-1980 -2080 840', screwm_clamp(152 + grid_signal * 186 + ceiling_pulse * 176, 118, 700), screwm_cyan);
    adddynamiclight('1980 -2080 840', screwm_clamp(152 + grid_signal * 186 + floor_pulse * 176, 118, 700), screwm_rose);
    adddynamiclight('0 -2480 840', screwm_clamp(138 + grid_signal * 178 + screwm_effect_drift_temporal * 184, 108, 680), screwm_amber);
};

void() screwm_add_expression_surface_lights =
{
    float pressure;
    float local_pressure;
    float floor_pressure;
    float wall_pressure;
    float ceiling_pressure;
    float void_pressure;
    vector roaming_color;

    if (cvar("screwm_csqc_full_expression_field") <= 0)
        return;
    if (!screwm_effect_lightfield_enabled())
        return;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();

    floor_pressure = screwm_clamp(
        0.42 + pressure * 1.08 + screwm_effect_drift_edge * 0.90 + screwm_effect_drift_fast_ratio * 0.54 + local_pressure * 0.58,
        0.34,
        3.0
    );
    wall_pressure = screwm_clamp(
        0.46 + pressure * 1.02 + screwm_effect_drift_texture * 0.84 + screwm_effect_drift_compositing * 0.70 + local_pressure * 0.56,
        0.36,
        3.0
    );
    ceiling_pressure = screwm_clamp(
        0.44 + pressure * 1.02 + screwm_effect_drift_temporal * 0.84 + screwm_effect_drift_slow_ratio * 0.66 + local_pressure * 0.48,
        0.36,
        3.0
    );
    void_pressure = screwm_clamp(
        0.40 + pressure * 0.96 + screwm_effect_drift_density_currency * 0.98 + screwm_effect_drift_atmospheric * 0.64,
        0.34,
        3.0
    );
    roaming_color = screwm_synthwave_color(time * 0.047 + screwm_effect_drift_region_count * 4.0);

    adddynamiclight('-1180 -1480 420', screwm_clamp(92 + wall_pressure * 216, 72, 620), screwm_cyan);
    adddynamiclight('1180 -1040 430', screwm_clamp(92 + wall_pressure * 212, 72, 610), screwm_rose);
    adddynamiclight('-1990 -1480 860', screwm_clamp(82 + wall_pressure * 198, 66, 580), roaming_color);
    adddynamiclight('1990 -1040 940', screwm_clamp(82 + wall_pressure * 194, 66, 570), roaming_color * 0.88);
    adddynamiclight('0 -2020 62', screwm_clamp(86 + floor_pressure * 214, 68, 620), screwm_amber);
    adddynamiclight('-520 -760 58', screwm_clamp(64 + floor_pressure * 166, 52, 500), screwm_green);
    adddynamiclight('0 -1420 1370', screwm_clamp(84 + ceiling_pressure * 218, 66, 620), screwm_cyan);
    adddynamiclight('640 420 1320', screwm_clamp(70 + ceiling_pressure * 180, 54, 520), screwm_green);
    adddynamiclight('-720 580 520', screwm_clamp(64 + void_pressure * 188, 50, 540), roaming_color);
    adddynamiclight('720 -2260 740', screwm_clamp(64 + void_pressure * 184, 50, 530), roaming_color * 0.82);
    adddynamiclight('0 -590 286', screwm_clamp(86 + pressure * 214 + local_pressure * 126, 64, 620), screwm_rose);
};

void() screwm_add_shadow_budget_lights =
{
    screwm_add_scroom_baseline_lights();
    screwm_add_hex_grid_drift_lights();
    screwm_add_entry_substrate_drift_lights();
    screwm_add_expression_surface_lights();
    screwm_add_media_source_signal_lights();
    screwm_add_aoa_pane_signal_lights();
    screwm_add_shadow_budget_edge_lights();
    screwm_add_aoa_drift_lights();
};

void(vector a, vector b, vector c, vector d, vector color, float alpha) screwm_draw_geometry_quad =
{
    R_BeginPolygon("geom_mark", DRAWFLAG_ADDITIVE, 0);
    R_PolygonVertex(a, '0 0 0', color, alpha);
    R_PolygonVertex(b, '1 0 0', color, alpha);
    R_PolygonVertex(c, '1 1 0', color, alpha);
    R_PolygonVertex(d, '0 1 0', color, alpha);
    R_EndPolygon();

    R_BeginPolygon("geom_mark", DRAWFLAG_ADDITIVE, 0);
    R_PolygonVertex(d, '0 1 0', color, alpha);
    R_PolygonVertex(c, '1 1 0', color, alpha);
    R_PolygonVertex(b, '1 0 0', color, alpha);
    R_PolygonVertex(a, '0 0 0', color, alpha);
    R_EndPolygon();
};

void(float cx, float cy, float z, float length, float width, float angle, vector color, float alpha) screwm_draw_xy_ribbon =
{
    vector center;
    vector dir;
    vector side;
    vector a;
    vector b;
    vector c;
    vector d;
    float half_len;
    float half_width;

    center = '0 0 0';
    center_x = cx;
    center_y = cy;
    center_z = z;
    dir = '0 0 0';
    dir_x = cos(angle);
    dir_y = sin(angle);
    side = '0 0 0';
    side_x = 0 - dir_y;
    side_y = dir_x;
    half_len = length * 0.5;
    half_width = width * 0.5;

    a = center - dir * half_len - side * half_width;
    b = center + dir * half_len - side * half_width;
    c = center + dir * half_len + side * half_width;
    d = center - dir * half_len + side * half_width;
    screwm_draw_geometry_quad(a, b, c, d, color, alpha);
};

void(float x, float cy, float cz, float length, float width, float angle, vector color, float alpha) screwm_draw_xz_wall_ribbon =
{
    vector center;
    vector dir;
    vector side;
    vector a;
    vector b;
    vector c;
    vector d;
    float half_len;
    float half_width;

    center = '0 0 0';
    center_x = x;
    center_y = cy;
    center_z = cz;
    dir = '0 0 0';
    dir_y = cos(angle);
    dir_z = sin(angle);
    side = '0 0 0';
    side_y = 0 - dir_z;
    side_z = dir_y;
    half_len = length * 0.5;
    half_width = width * 0.5;

    a = center - dir * half_len - side * half_width;
    b = center + dir * half_len - side * half_width;
    c = center + dir * half_len + side * half_width;
    d = center - dir * half_len + side * half_width;
    screwm_draw_geometry_quad(a, b, c, d, color, alpha);
};

void(float y, float cx, float cz, float length, float width, float angle, vector color, float alpha) screwm_draw_yz_wall_ribbon =
{
    vector center;
    vector dir;
    vector side;
    vector a;
    vector b;
    vector c;
    vector d;
    float half_len;
    float half_width;

    center = '0 0 0';
    center_x = cx;
    center_y = y;
    center_z = cz;
    dir = '0 0 0';
    dir_x = cos(angle);
    dir_z = sin(angle);
    side = '0 0 0';
    side_x = 0 - dir_z;
    side_z = dir_x;
    half_len = length * 0.5;
    half_width = width * 0.5;

    a = center - dir * half_len - side * half_width;
    b = center + dir * half_len - side * half_width;
    c = center + dir * half_len + side * half_width;
    d = center - dir * half_len + side * half_width;
    screwm_draw_geometry_quad(a, b, c, d, color, alpha);
};

void(vector a, vector b, vector c, vector d, vector color, float alpha) screwm_draw_drift_quad =
{
    R_BeginPolygon("drift_c", DRAWFLAG_ADDITIVE, 0);
    R_PolygonVertex(a, '0 0 0', color, alpha);
    R_PolygonVertex(b, '1 0 0', color, alpha);
    R_PolygonVertex(c, '1 1 0', color, alpha);
    R_PolygonVertex(d, '0 1 0', color, alpha);
    R_EndPolygon();

    R_BeginPolygon("drift_c", DRAWFLAG_ADDITIVE, 0);
    R_PolygonVertex(d, '0 1 0', color, alpha);
    R_PolygonVertex(c, '1 1 0', color, alpha);
    R_PolygonVertex(b, '1 0 0', color, alpha);
    R_PolygonVertex(a, '0 0 0', color, alpha);
    R_EndPolygon();
};

void(float cx, float cy, float z, float length, float width, float angle, vector color, float alpha) screwm_draw_drift_xy_ribbon =
{
    vector center;
    vector dir;
    vector side;
    vector a;
    vector b;
    vector c;
    vector d;
    float half_len;
    float half_width;

    center = '0 0 0';
    center_x = cx;
    center_y = cy;
    center_z = z;
    dir = '0 0 0';
    dir_x = cos(angle);
    dir_y = sin(angle);
    side = '0 0 0';
    side_x = 0 - dir_y;
    side_y = dir_x;
    half_len = length * 0.5;
    half_width = width * 0.5;

    a = center - dir * half_len - side * half_width;
    b = center + dir * half_len - side * half_width;
    c = center + dir * half_len + side * half_width;
    d = center - dir * half_len + side * half_width;
    screwm_draw_drift_quad(a, b, c, d, color, alpha);
};

void(float x, float cy, float cz, float length, float width, float angle, vector color, float alpha) screwm_draw_drift_xz_wall_ribbon =
{
    vector center;
    vector dir;
    vector side;
    vector a;
    vector b;
    vector c;
    vector d;
    float half_len;
    float half_width;

    center = '0 0 0';
    center_x = x;
    center_y = cy;
    center_z = cz;
    dir = '0 0 0';
    dir_y = cos(angle);
    dir_z = sin(angle);
    side = '0 0 0';
    side_y = 0 - dir_z;
    side_z = dir_y;
    half_len = length * 0.5;
    half_width = width * 0.5;

    a = center - dir * half_len - side * half_width;
    b = center + dir * half_len - side * half_width;
    c = center + dir * half_len + side * half_width;
    d = center - dir * half_len + side * half_width;
    screwm_draw_drift_quad(a, b, c, d, color, alpha);
};

void(float y, float cx, float cz, float length, float width, float angle, vector color, float alpha) screwm_draw_drift_yz_wall_ribbon =
{
    vector center;
    vector dir;
    vector side;
    vector a;
    vector b;
    vector c;
    vector d;
    float half_len;
    float half_width;

    center = '0 0 0';
    center_x = cx;
    center_y = y;
    center_z = cz;
    dir = '0 0 0';
    dir_x = cos(angle);
    dir_z = sin(angle);
    side = '0 0 0';
    side_x = 0 - dir_z;
    side_z = dir_x;
    half_len = length * 0.5;
    half_width = width * 0.5;

    a = center - dir * half_len - side * half_width;
    b = center + dir * half_len - side * half_width;
    c = center + dir * half_len + side * half_width;
    d = center - dir * half_len + side * half_width;
    screwm_draw_drift_quad(a, b, c, d, color, alpha);
};

void(float z, float phase, float width, float alpha, float phase_bias) screwm_draw_hex_light_grid_plane =
{
    float i;
    float offset;
    float drift;
    vector color_a;
    vector color_b;
    vector color_c;

    i = -3;
    while (i <= 3)
    {
        offset = i * 332;
        drift = sin(phase * 0.47 + i * 0.91) * 46;
        color_a = screwm_synthwave_color(phase + phase_bias + i * 0.22);
        color_b = screwm_synthwave_color(phase + phase_bias + 1.8 + i * 0.17);
        color_c = screwm_synthwave_color(phase + phase_bias + 3.4 + i * 0.19);

        screwm_draw_drift_xy_ribbon(0, -555 + offset + drift, z, 3580, width, 0.000, color_a, alpha);
        screwm_draw_drift_xy_ribbon(offset * 0.36, -555 + offset * 0.58 - drift, z, 3320, width * 0.86, 1.047, color_b, alpha * 0.78);
        screwm_draw_drift_xy_ribbon(0 - offset * 0.36, -555 + offset * 0.58 + drift, z, 3320, width * 0.86, 2.094, color_c, alpha * 0.74);
        i = i + 1;
    }
};

void(float phase, float width, float alpha) screwm_draw_wall_light_grid_planes =
{
    float i;
    float z;
    float y;
    float x;
    float drift;
    vector color_a;
    vector color_b;

    i = 0;
    while (i < 6)
    {
        z = 260 + i * 262;
        drift = sin(phase * 0.39 + i * 0.77) * 34;
        color_a = screwm_synthwave_color(phase + i * 0.31);
        color_b = screwm_synthwave_color(phase + 2.2 + i * 0.29);

        screwm_draw_drift_xz_wall_ribbon(2046, -555 + drift, z, 3540, width * 0.70, 0.000, color_a, alpha * 0.62);
        screwm_draw_drift_xz_wall_ribbon(-2046, -555 - drift, z, 3540, width * 0.70, 0.000, color_b, alpha * 0.62);
        screwm_draw_drift_yz_wall_ribbon(1420, drift, z, 3600, width * 0.68, 0.000, color_b, alpha * 0.58);
        screwm_draw_drift_yz_wall_ribbon(-2532, 0 - drift, z, 3600, width * 0.68, 0.000, color_a, alpha * 0.58);
        i = i + 1;
    }

    i = -3;
    while (i <= 3)
    {
        y = -555 + i * 420;
        x = i * 580;
        drift = cos(phase * 0.43 + i * 0.83) * 38;
        color_a = screwm_synthwave_color(phase + 0.8 + i * 0.23);
        color_b = screwm_synthwave_color(phase + 2.9 + i * 0.27);

        screwm_draw_drift_xz_wall_ribbon(2045, y + drift, 850, 1510, width * 0.60, 1.570, color_a, alpha * 0.54);
        screwm_draw_drift_xz_wall_ribbon(-2045, y - drift, 850, 1510, width * 0.60, 1.570, color_b, alpha * 0.54);
        screwm_draw_drift_yz_wall_ribbon(1419, x + drift, 850, 1510, width * 0.58, 1.570, color_b, alpha * 0.50);
        screwm_draw_drift_yz_wall_ribbon(-2531, x - drift, 850, 1510, width * 0.58, 1.570, color_a, alpha * 0.50);
        i = i + 1;
    }
};

void() screwm_draw_hex_alignment_light_grid =
{
    float pressure;
    float local_pressure;
    float signal;
    float phase;
    float pulse;
    float width;
    float alpha;

    if (cvar("screwm_csqc_full_expression_field") <= 0)
        return;
    if (!screwm_effect_lightfield_enabled())
        return;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();
    signal = screwm_clamp(
        0.56 + pressure * 1.02 + local_pressure * 0.64 + screwm_effect_drift_edge * 1.12 + screwm_effect_drift_texture * 0.78 + screwm_effect_drift_fast_ratio * 0.46 + screwm_effect_drift_compositing * 0.36,
        0.46,
        3.4
    );
    phase = time * (0.42 + screwm_effect_drift_fast_ratio * 0.20) + screwm_effect_drift_kind_variance * 4.7 + screwm_effect_drift_max_delta * 2.2;
    pulse = 0.50 + 0.50 * sin(phase * 0.89 + screwm_effect_drift_temporal * 2.8);
    width = screwm_clamp(5 + screwm_effect_drift_edge * 6 + screwm_effect_drift_texture * 5 + pulse * 6, 4, 16);
    alpha = screwm_clamp(0.10 + signal * 0.035 + pulse * 0.11, 0.10, 0.32);

    screwm_draw_hex_light_grid_plane(-49, phase, width, alpha, 0.0);
    screwm_draw_hex_light_grid_plane(1757, phase, width * 0.92, alpha * 0.88, 2.1);
    screwm_draw_wall_light_grid_planes(phase, width, alpha * 0.96);
};

void() screwm_draw_media_receiver_drift_fields =
{
    float pressure;
    float local_pressure;
    float signal;
    float phase;
    float pulse_a;
    float pulse_b;
    float pulse_c;
    float alpha;
    float halo_alpha;
    float flash_a;
    float flash_b;
    float floor_alpha;
    float ceiling_alpha;
    float source_alpha;
    float width;
    float fine_width;
    float sweep_width;
    vector color_a;
    vector color_b;
    vector color_c;

    if (cvar("screwm_csqc_full_expression_field") <= 0)
        return;
    if (!screwm_effect_lightfield_enabled())
        return;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();
    signal = screwm_clamp(
        0.58 + pressure * 1.10 + local_pressure * 0.66 + screwm_effect_drift_active_slot_ratio * 0.74 + screwm_effect_drift_edge * 1.18 + screwm_effect_drift_texture * 0.84 + screwm_effect_drift_compositing * 0.74 + screwm_effect_drift_density_currency * 0.44,
        0.48,
        3.8
    );
    phase = time * (1.02 + screwm_effect_drift_fast_ratio * 0.52) + screwm_effect_drift_kind_variance * 7.4 + screwm_effect_drift_max_delta * 3.6;
    pulse_a = 0.50 + 0.50 * sin(phase);
    pulse_b = 0.50 + 0.50 * cos(phase * 0.71 + screwm_effect_drift_temporal * 4.6);
    pulse_c = 0.50 + 0.50 * sin(phase * 1.29 + screwm_effect_drift_density_currency * 5.8);
    flash_a = 0.50 + 0.50 * sin(phase * 2.37 + screwm_effect_drift_fast_ratio * 4.0);
    flash_b = 0.50 + 0.50 * cos(phase * 2.11 + screwm_effect_drift_texture * 5.0);
    alpha = screwm_clamp(0.24 + signal * 0.12 + pulse_a * 0.42, 0.30, 0.96);
    halo_alpha = screwm_clamp(0.20 + signal * 0.10 + pulse_b * 0.36, 0.26, 0.88);
    source_alpha = screwm_clamp(0.26 + signal * 0.12 + flash_a * 0.54, 0.34, 1.00);
    floor_alpha = screwm_clamp(0.22 + signal * 0.10 + flash_b * 0.60, 0.30, 0.96);
    ceiling_alpha = screwm_clamp(0.22 + signal * 0.10 + flash_a * 0.58, 0.30, 0.96);
    width = screwm_clamp(24 + screwm_effect_drift_edge * 20 + screwm_effect_drift_texture * 16 + pulse_b * 24, 24, 78);
    fine_width = screwm_clamp(12 + screwm_effect_drift_edge * 10 + screwm_effect_drift_texture * 8 + pulse_c * 14, 12, 42);
    sweep_width = screwm_clamp(34 + screwm_effect_drift_edge * 20 + screwm_effect_drift_texture * 18 + flash_a * 30, 34, 96);
    color_a = screwm_synthwave_color(phase + 0.5);
    color_b = screwm_synthwave_color(phase + 2.4);
    color_c = screwm_synthwave_color(phase + 4.7);

    screwm_draw_drift_xz_wall_ribbon(-1580, -1320 + sin(phase * 1.21) * 86, 260 + cos(phase * 0.97) * 54, 900, width, 1.570, color_a, alpha);
    screwm_draw_xz_wall_ribbon(-1578, -1320 + cos(phase * 1.89) * 260, 260 + sin(phase * 1.61) * 118, 1180, sweep_width, 1.570 + sin(phase * 0.31) * 0.42, color_a, source_alpha);
    screwm_draw_drift_xz_wall_ribbon(-1582, -1320 + cos(phase * 1.17) * 140, 230 + sin(phase * 1.03) * 48, 720, fine_width * 1.08, 0.000, color_b, halo_alpha);
    screwm_draw_xz_wall_ribbon(-1576, -1280 + sin(phase * 1.73) * 300, 210 + cos(phase * 1.47) * 94, 980, fine_width * 1.42, sin(phase * 0.37) * 0.76, color_c, source_alpha * 0.84);
    screwm_draw_drift_xz_wall_ribbon(-1584, -2140 + sin(phase * 0.83) * 118, 320 + cos(phase * 0.91) * 62, 760, fine_width, 1.240, color_c, halo_alpha * 0.90);
    screwm_draw_drift_xz_wall_ribbon(-1584, -500 + cos(phase * 0.89) * 112, 330 + sin(phase * 0.87) * 58, 700, fine_width, 0.340, '1.00 0.78 0.92', halo_alpha * 0.86);
    screwm_draw_drift_xz_wall_ribbon(1580, -1320 + cos(phase * 1.19) * 86, 260 + sin(phase * 0.95) * 54, 900, width, 1.570, color_b, alpha);
    screwm_draw_xz_wall_ribbon(1578, -1320 + sin(phase * 1.87) * 260, 260 + cos(phase * 1.59) * 118, 1180, sweep_width, 1.570 + cos(phase * 0.29) * 0.42, color_b, source_alpha);
    screwm_draw_drift_xz_wall_ribbon(1582, -1320 + sin(phase * 1.13) * 140, 230 + cos(phase * 1.05) * 48, 720, fine_width * 1.08, 0.000, color_c, halo_alpha);
    screwm_draw_xz_wall_ribbon(1576, -1280 + cos(phase * 1.71) * 300, 210 + sin(phase * 1.49) * 94, 980, fine_width * 1.42, cos(phase * 0.35) * 0.76, color_a, source_alpha * 0.84);
    screwm_draw_drift_xz_wall_ribbon(1584, -2140 + cos(phase * 0.81) * 118, 320 + sin(phase * 0.93) * 62, 760, fine_width, 0.910, color_a, halo_alpha * 0.90);
    screwm_draw_drift_xz_wall_ribbon(1584, -500 + sin(phase * 0.87) * 112, 330 + cos(phase * 0.89) * 58, 700, fine_width, 2.780, '0.78 1.00 0.92', halo_alpha * 0.86);

    screwm_draw_drift_xy_ribbon(-1040 + sin(phase * 0.59) * 120, -1480, -48, 1320, fine_width * 0.92, 0.520, color_c, halo_alpha * 0.84);
    screwm_draw_xy_ribbon(-1040 + sin(phase * 1.93) * 560, -1480 + cos(phase * 1.37) * 340, -47, 1520, sweep_width * 0.86, 0.520 + sin(phase * 0.41) * 0.82, color_c, floor_alpha);
    screwm_draw_xy_ribbon(-1320 + cos(phase * 1.79) * 620, -1180 + sin(phase * 1.43) * 360, -46, 1180, fine_width * 1.44, 2.094 + cos(phase * 0.33) * 0.74, '1.00 0.78 0.92', floor_alpha * 0.88);
    screwm_draw_drift_xy_ribbon(-1280 + cos(phase * 0.67) * 160, -1290, 1756, 1120, fine_width * 0.84, 1.047, color_a, halo_alpha * 0.78);
    screwm_draw_xy_ribbon(-1120 + cos(phase * 1.83) * 580, -1320 + sin(phase * 1.31) * 360, 1756, 1420, sweep_width * 0.76, 1.047 + cos(phase * 0.39) * 0.72, color_a, ceiling_alpha);
    screwm_draw_xy_ribbon(-1540 + sin(phase * 1.69) * 520, -940 + cos(phase * 1.27) * 300, 1755, 980, fine_width * 1.34, 0.000 + sin(phase * 0.45) * 0.68, '0.82 1.00 0.92', ceiling_alpha * 0.86);
    screwm_draw_drift_xy_ribbon(1040 + cos(phase * 0.61) * 120, -1480, -48, 1320, fine_width * 0.92, 2.620, color_a, halo_alpha * 0.84);
    screwm_draw_xy_ribbon(1040 + cos(phase * 1.91) * 560, -1480 + sin(phase * 1.35) * 340, -47, 1520, sweep_width * 0.86, 2.620 + cos(phase * 0.43) * 0.82, color_a, floor_alpha);
    screwm_draw_xy_ribbon(1320 + sin(phase * 1.77) * 620, -1180 + cos(phase * 1.41) * 360, -46, 1180, fine_width * 1.44, 1.047 + sin(phase * 0.35) * 0.74, '0.82 1.00 0.92', floor_alpha * 0.88);
    screwm_draw_drift_xy_ribbon(1280 + sin(phase * 0.69) * 160, -1290, 1756, 1120, fine_width * 0.84, 2.094, color_b, halo_alpha * 0.78);
    screwm_draw_xy_ribbon(1120 + sin(phase * 1.81) * 580, -1320 + cos(phase * 1.29) * 360, 1756, 1420, sweep_width * 0.76, 2.094 + sin(phase * 0.37) * 0.72, color_b, ceiling_alpha);
    screwm_draw_xy_ribbon(1540 + cos(phase * 1.67) * 520, -940 + sin(phase * 1.25) * 300, 1755, 980, fine_width * 1.34, 0.000 + cos(phase * 0.47) * 0.68, '1.00 0.82 0.92', ceiling_alpha * 0.86);

    screwm_draw_drift_xy_ribbon(0, -555 + sin(phase * 0.47) * 96, -47, 1180, fine_width * 0.86, 0.000, '0.86 1.00 0.76', halo_alpha * 0.82);
    screwm_draw_drift_xy_ribbon(0, -555 + cos(phase * 0.43) * 92, 1756, 1180, fine_width * 0.86, 1.047, '0.82 0.96 1.00', halo_alpha * 0.78);
    screwm_draw_drift_yz_wall_ribbon(-596, sin(phase * 0.73) * 180, 224 + cos(phase * 0.79) * 72, 760, fine_width, 1.570, color_c, halo_alpha * 0.72);
};

void() screwm_draw_geometry_edge_pulses =
{
    float pressure;
    float local_pressure;
    float signal;
    float phase;
    float pulse_a;
    float pulse_b;
    float alpha_a;
    float alpha_b;
    vector roam_a;
    vector roam_b;

    if (cvar("screwm_csqc_full_expression_field") <= 0)
        return;
    if (!screwm_effect_lightfield_enabled())
        return;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();
    signal = screwm_clamp(
        0.52 + pressure * 0.96 + local_pressure * 0.62 + screwm_effect_drift_edge * 1.18 + screwm_effect_drift_texture * 0.76 + screwm_effect_drift_density_currency * 0.72,
        0.42,
        3.4
    );
    phase = time * (0.76 + screwm_effect_drift_fast_ratio * 0.28) + screwm_effect_drift_kind_variance * 5.2 + screwm_effect_drift_max_delta * 2.5;
    pulse_a = 0.50 + 0.50 * sin(phase);
    pulse_b = 0.50 + 0.50 * cos(phase * 0.71 + screwm_effect_drift_temporal * 3.4);
    alpha_a = screwm_clamp(0.20 + signal * 0.10 + pulse_a * 0.34, 0.26, 0.90);
    alpha_b = screwm_clamp(0.18 + signal * 0.09 + pulse_b * 0.31, 0.24, 0.84);
    roam_a = screwm_synthwave_color(phase + 0.4);
    roam_b = screwm_synthwave_color(phase + 2.2);

    screwm_draw_xy_ribbon(0, -2320, -58, 2040, 34, 0.000, roam_a, alpha_a);
    screwm_draw_xy_ribbon(0, -2250, -57, 1780, 30, 1.047, screwm_amber, alpha_b);
    screwm_draw_xy_ribbon(0, -2250, -56, 1780, 30, 2.094, screwm_green, alpha_a * 0.92);
    screwm_draw_xy_ribbon(0, -1880, -57, 1460, 28, 0.520, screwm_cyan, alpha_b * 0.88);
    screwm_draw_xy_ribbon(0, -2320, 1754, 2040, 34, 0.000, roam_b, alpha_b);
    screwm_draw_xy_ribbon(0, -2160, 1753, 1780, 30, 1.047, screwm_cyan, alpha_a);
    screwm_draw_xy_ribbon(0, -2160, 1752, 1780, 30, 2.094, screwm_rose, alpha_b * 0.94);
    screwm_draw_xy_ribbon(0, -1880, 1753, 1460, 28, 0.520, screwm_amber, alpha_a * 0.84);

    screwm_draw_xy_ribbon(920, -1040, -57, 1320, 28, 0.520, roam_a, alpha_a * 0.94);
    screwm_draw_xy_ribbon(920, -1040, 1753, 1320, 28, 0.520, roam_b, alpha_b * 0.94);
    screwm_draw_xy_ribbon(-920, -1040, -57, 1320, 28, 2.620, screwm_green, alpha_b * 0.92);
    screwm_draw_xy_ribbon(-920, -1040, 1753, 1320, 28, 2.620, screwm_cyan, alpha_a * 0.92);

    screwm_draw_xz_wall_ribbon(2056, -1640, 720, 1720, 28, 1.230, screwm_rose, alpha_a);
    screwm_draw_xz_wall_ribbon(2055, -2140, 980, 1480, 26, 0.430, roam_b, alpha_b);
    screwm_draw_xz_wall_ribbon(-2056, -1640, 720, 1720, 28, 1.910, screwm_cyan, alpha_b);
    screwm_draw_xz_wall_ribbon(-2055, -2140, 980, 1480, 26, 2.610, roam_a, alpha_a);
    screwm_draw_yz_wall_ribbon(1423, 0, 920, 2540, 30, 0.000, roam_b, alpha_b);
    screwm_draw_yz_wall_ribbon(1424, -820, 740, 1280, 24, 0.780, screwm_cyan, alpha_a * 0.86);
    screwm_draw_yz_wall_ribbon(1424, 820, 740, 1280, 24, 2.360, screwm_rose, alpha_b * 0.86);
};

void() screwm_draw_entry_threshold_substrate_pulses =
{
    float pressure;
    float local_pressure;
    float signal;
    float phase;
    float pulse_a;
    float pulse_b;
    float pulse_c;
    float alpha_ceiling;
    float alpha_wall;
    float alpha_void;
    float width;
    float ceiling_width;
    float ceiling_trace_width;
    float ceiling_alpha;
    float ceiling_stipple_alpha;
    float ceiling_z;
    float kinetic_alpha;
    float ceiling_knot_alpha;
    float ceiling_knot_width;
    float right_wall_alpha;
    float right_wall_width;
    vector color_a;
    vector color_b;
    vector color_c;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();
    signal = screwm_clamp(
        0.44 + pressure * 0.74 + local_pressure * 0.46 + screwm_effect_drift_active_ratio * 0.70 + screwm_effect_drift_edge * 0.96 + screwm_effect_drift_texture * 0.52 + screwm_effect_drift_temporal * 0.48,
        0.24,
        3.2
    );
    phase = time * (1.68 + screwm_effect_drift_fast_ratio * 0.72) + screwm_effect_drift_kind_variance * 6.4 + screwm_effect_drift_max_delta * 3.1;
    pulse_a = 0.50 + 0.50 * sin(phase);
    pulse_b = 0.50 + 0.50 * cos(phase * 0.63 + screwm_effect_drift_temporal * 5.1);
    pulse_c = 0.50 + 0.50 * sin(phase * 1.31 + screwm_effect_drift_density_currency * 6.2);
    alpha_ceiling = screwm_clamp(0.24 + signal * 0.13 + pulse_a * 0.54, 0.26, 1.00);
    alpha_wall = screwm_clamp(0.22 + signal * 0.12 + pulse_b * 0.46, 0.24, 0.94);
    alpha_void = screwm_clamp(0.22 + signal * 0.11 + pulse_c * 0.44, 0.24, 0.92);
    width = screwm_clamp(20 + screwm_effect_drift_edge * 22 + screwm_effect_drift_texture * 18 + pulse_a * 16, 20, 54);
    ceiling_width = screwm_clamp(68 + screwm_effect_drift_edge * 26 + screwm_effect_drift_texture * 18 + pulse_b * 30, 68, 132);
    ceiling_trace_width = screwm_clamp(18 + screwm_effect_drift_edge * 14 + screwm_effect_drift_texture * 10 + pulse_c * 16, 18, 54);
    ceiling_alpha = screwm_clamp(alpha_ceiling * 1.14, 0.34, 0.94);
    ceiling_stipple_alpha = screwm_clamp(0.74 + pulse_b * 0.26, 0.74, 1.00);
    ceiling_z = 1758;
    kinetic_alpha = screwm_clamp(0.82 + pulse_c * 0.18, 0.82, 1.00);
    ceiling_knot_alpha = screwm_clamp(0.90 + pulse_a * 0.10, 0.90, 1.00);
    ceiling_knot_width = screwm_clamp(34 + screwm_effect_drift_edge * 12 + screwm_effect_drift_texture * 8 + pulse_a * 24, 34, 78);
    right_wall_alpha = screwm_clamp(0.78 + pulse_a * 0.22, 0.78, 1.00);
    right_wall_width = screwm_clamp(24 + screwm_effect_drift_edge * 10 + screwm_effect_drift_texture * 8 + pulse_b * 22, 24, 64);
    color_a = screwm_synthwave_color(phase + 0.7);
    color_b = screwm_synthwave_color(phase + 2.8);
    color_c = screwm_synthwave_color(phase + 4.9);

    screwm_draw_drift_xy_ribbon(0, -2380, ceiling_z, 3600, ceiling_width * 0.54, 0.000, color_b, ceiling_alpha * 0.72);
    screwm_draw_drift_xy_ribbon(sin(phase * 0.31) * 120, -2300, ceiling_z - 1, 3200, ceiling_width * 0.44, 1.047, color_c, ceiling_alpha * 0.66);
    screwm_draw_drift_xy_ribbon(cos(phase * 0.33) * 120, -2240, ceiling_z - 2, 3200, ceiling_width * 0.44, 2.094, color_a, ceiling_alpha * 0.62);
    screwm_draw_drift_xy_ribbon(sin(phase * 0.91) * 420, -2620, ceiling_z, 4240, ceiling_trace_width, 0.000, color_b, ceiling_alpha);
    screwm_draw_drift_xy_ribbon(cos(phase * 0.87) * 420, -2420, ceiling_z - 1, 3920, ceiling_trace_width * 0.92, 1.047, color_c, ceiling_alpha * 0.92);
    screwm_draw_drift_xy_ribbon(sin(phase * 0.83) * 360, -2220, ceiling_z - 2, 3920, ceiling_trace_width * 0.86, 2.094, color_a, ceiling_alpha * 0.84);
    screwm_draw_drift_xy_ribbon(-1760 + sin(phase * 1.03) * 260, -2480, ceiling_z, 1240, ceiling_trace_width * 1.12, 0.000, '0.86 0.98 1.00', ceiling_alpha);
    screwm_draw_drift_xy_ribbon(1760 + cos(phase * 1.01) * 260, -2480, ceiling_z, 1240, ceiling_trace_width * 1.08, 0.000, '1.00 0.86 0.62', ceiling_alpha * 0.94);
    screwm_draw_drift_xy_ribbon(-1640 + cos(phase * 0.79) * 300, -2140, ceiling_z - 1, 1240, ceiling_trace_width * 0.96, 1.047, '0.84 1.00 0.82', ceiling_alpha * 0.86);
    screwm_draw_drift_xy_ribbon(1640 + sin(phase * 0.77) * 300, -2140, ceiling_z - 1, 1240, ceiling_trace_width * 0.96, 2.094, '1.00 0.78 0.92', ceiling_alpha * 0.84);
    screwm_draw_drift_xy_ribbon(-1120 + sin(phase * 1.23) * 220, -1860 + cos(phase * 0.71) * 120, ceiling_z, 220, ceiling_trace_width * 1.38, 0.000, '1.00 0.90 0.64', ceiling_stipple_alpha);
    screwm_draw_drift_xy_ribbon(-620 + cos(phase * 1.19) * 210, -1700 + sin(phase * 0.83) * 120, ceiling_z, 180, ceiling_trace_width * 1.22, 1.047, '0.66 0.98 1.00', ceiling_stipple_alpha * 0.94);
    screwm_draw_drift_xy_ribbon(0 + sin(phase * 1.31) * 240, -1580 + cos(phase * 0.91) * 128, ceiling_z, 240, ceiling_trace_width * 1.42, 2.094, '1.00 0.64 0.96', ceiling_stipple_alpha);
    screwm_draw_drift_xy_ribbon(640 + cos(phase * 1.17) * 210, -1720 + sin(phase * 0.79) * 120, ceiling_z, 180, ceiling_trace_width * 1.22, 1.047, '0.84 1.00 0.72', ceiling_stipple_alpha * 0.92);
    screwm_draw_drift_xy_ribbon(1120 + sin(phase * 1.29) * 220, -1880 + cos(phase * 0.73) * 120, ceiling_z, 220, ceiling_trace_width * 1.38, 0.000, '1.00 0.82 0.64', ceiling_stipple_alpha * 0.96);
    screwm_draw_drift_xy_ribbon(-1480 + cos(phase * 1.07) * 260, -2320 + sin(phase * 0.67) * 140, ceiling_z, 260, ceiling_trace_width * 1.32, 2.094, '0.66 0.94 1.00', ceiling_stipple_alpha * 0.96);
    screwm_draw_drift_xy_ribbon(-420 + sin(phase * 1.41) * 260, -2360 + cos(phase * 0.69) * 150, ceiling_z, 260, ceiling_trace_width * 1.36, 0.000, '1.00 0.68 0.98', ceiling_stipple_alpha);
    screwm_draw_drift_xy_ribbon(420 + cos(phase * 1.37) * 260, -2360 + sin(phase * 0.77) * 150, ceiling_z, 260, ceiling_trace_width * 1.36, 0.000, '0.76 1.00 0.72', ceiling_stipple_alpha * 0.96);
    screwm_draw_drift_xy_ribbon(1480 + sin(phase * 1.11) * 260, -2320 + cos(phase * 0.81) * 140, ceiling_z, 260, ceiling_trace_width * 1.32, 1.047, '1.00 0.78 0.62', ceiling_stipple_alpha * 0.94);
    screwm_draw_xy_ribbon(sin(phase * 1.09) * 520, -2500, ceiling_z, 4240, ceiling_trace_width * 1.74, 0.000, color_b, ceiling_stipple_alpha);
    screwm_draw_xy_ribbon(cos(phase * 1.03) * 520, -2260, ceiling_z, 3920, ceiling_trace_width * 1.48, 1.047, color_c, ceiling_stipple_alpha * 0.94);
    screwm_draw_xy_ribbon(sin(phase * 1.15) * 480, -2020, ceiling_z, 3920, ceiling_trace_width * 1.44, 2.094, color_a, ceiling_stipple_alpha * 0.90);
    screwm_draw_xy_ribbon(-1560 + sin(phase * 1.41) * 320, -2360, ceiling_z, 980, ceiling_trace_width * 1.70, 0.000, '0.94 1.00 0.78', ceiling_stipple_alpha);
    screwm_draw_xy_ribbon(1560 + cos(phase * 1.37) * 320, -2360, ceiling_z, 980, ceiling_trace_width * 1.70, 0.000, '1.00 0.76 0.92', ceiling_stipple_alpha * 0.96);
    screwm_draw_drift_xy_ribbon(-1180 + sin(phase * 1.53) * 180, -1460 + cos(phase * 0.97) * 92, ceiling_z, 260, ceiling_trace_width * 1.58, 0.000, '0.76 1.00 0.88', kinetic_alpha);
    screwm_draw_drift_xy_ribbon(-720 + cos(phase * 1.49) * 170, -1320 + sin(phase * 1.01) * 86, ceiling_z, 220, ceiling_trace_width * 1.44, 1.047, '1.00 0.72 0.96', kinetic_alpha * 0.96);
    screwm_draw_drift_xy_ribbon(-220 + sin(phase * 1.61) * 190, -1180 + cos(phase * 0.89) * 84, ceiling_z, 260, ceiling_trace_width * 1.54, 2.094, '0.70 0.96 1.00', kinetic_alpha);
    screwm_draw_drift_xy_ribbon(360 + cos(phase * 1.57) * 180, -1270 + sin(phase * 0.93) * 92, ceiling_z, 240, ceiling_trace_width * 1.46, 0.000, '1.00 0.88 0.62', kinetic_alpha * 0.98);
    screwm_draw_drift_xy_ribbon(980 + sin(phase * 1.43) * 170, -1500 + cos(phase * 0.87) * 88, ceiling_z, 240, ceiling_trace_width * 1.48, 1.047, '0.84 1.00 0.74', kinetic_alpha * 0.94);
    screwm_draw_drift_xy_ribbon(-960 + cos(phase * 1.67) * 160, -1840 + sin(phase * 0.91) * 96, ceiling_z, 180, ceiling_trace_width * 1.32, 2.094, '1.00 0.80 0.66', kinetic_alpha * 0.92);
    screwm_draw_drift_xy_ribbon(0 + sin(phase * 1.71) * 210, -1740 + cos(phase * 0.95) * 104, ceiling_z, 210, ceiling_trace_width * 1.40, 0.000, '0.72 1.00 0.96', kinetic_alpha);
    screwm_draw_drift_xy_ribbon(960 + cos(phase * 1.63) * 160, -1840 + sin(phase * 0.99) * 96, ceiling_z, 180, ceiling_trace_width * 1.32, 1.047, '1.00 0.70 0.96', kinetic_alpha * 0.92);
    screwm_draw_xy_ribbon(-1040 + cos(phase * 1.73) * 150, -1540 + sin(phase * 1.07) * 82, ceiling_z, 210, ceiling_trace_width * 1.34, 1.047, color_b, kinetic_alpha * 0.88);
    screwm_draw_xy_ribbon(-360 + sin(phase * 1.79) * 160, -1390 + cos(phase * 1.03) * 86, ceiling_z, 190, ceiling_trace_width * 1.28, 0.000, color_c, kinetic_alpha * 0.84);
    screwm_draw_xy_ribbon(540 + cos(phase * 1.69) * 160, -1400 + sin(phase * 1.05) * 84, ceiling_z, 190, ceiling_trace_width * 1.28, 2.094, color_a, kinetic_alpha * 0.84);
    screwm_draw_xy_ribbon(1180 + sin(phase * 1.75) * 150, -1540 + cos(phase * 1.09) * 82, ceiling_z, 210, ceiling_trace_width * 1.34, 1.047, color_b, kinetic_alpha * 0.88);
    screwm_draw_drift_xy_ribbon(-1260 + sin(phase * 2.11) * 130, -860 + cos(phase * 1.21) * 68, ceiling_z, 160, ceiling_knot_width, 0.000, '0.74 1.00 0.96', ceiling_knot_alpha);
    screwm_draw_drift_xy_ribbon(-820 + cos(phase * 2.03) * 128, -760 + sin(phase * 1.29) * 72, ceiling_z, 150, ceiling_knot_width * 0.92, 1.047, '1.00 0.70 0.94', ceiling_knot_alpha * 0.96);
    screwm_draw_drift_xy_ribbon(-380 + sin(phase * 2.17) * 136, -690 + cos(phase * 1.33) * 70, ceiling_z, 170, ceiling_knot_width * 0.98, 2.094, '0.82 0.96 1.00', ceiling_knot_alpha);
    screwm_draw_drift_xy_ribbon(80 + cos(phase * 2.23) * 142, -660 + sin(phase * 1.27) * 76, ceiling_z, 170, ceiling_knot_width, 0.000, '1.00 0.88 0.62', ceiling_knot_alpha);
    screwm_draw_drift_xy_ribbon(560 + sin(phase * 2.07) * 134, -720 + cos(phase * 1.31) * 72, ceiling_z, 150, ceiling_knot_width * 0.94, 1.047, '0.84 1.00 0.72', ceiling_knot_alpha * 0.98);
    screwm_draw_drift_xy_ribbon(1040 + cos(phase * 2.19) * 130, -840 + sin(phase * 1.25) * 70, ceiling_z, 160, ceiling_knot_width, 2.094, '1.00 0.76 0.92', ceiling_knot_alpha * 0.96);
    screwm_draw_xy_ribbon(-1080 + cos(phase * 2.29) * 118, -1080 + sin(phase * 1.37) * 74, ceiling_z, 140, ceiling_knot_width * 0.86, 1.047, color_a, ceiling_knot_alpha * 0.82);
    screwm_draw_xy_ribbon(-520 + sin(phase * 2.31) * 122, -980 + cos(phase * 1.41) * 72, ceiling_z, 130, ceiling_knot_width * 0.82, 0.000, color_b, ceiling_knot_alpha * 0.80);
    screwm_draw_xy_ribbon(360 + cos(phase * 2.27) * 122, -980 + sin(phase * 1.39) * 72, ceiling_z, 130, ceiling_knot_width * 0.82, 2.094, color_c, ceiling_knot_alpha * 0.80);
    screwm_draw_xy_ribbon(1040 + sin(phase * 2.33) * 118, -1080 + cos(phase * 1.35) * 74, ceiling_z, 140, ceiling_knot_width * 0.86, 1.047, color_a, ceiling_knot_alpha * 0.82);
    screwm_draw_xy_ribbon(sin(phase * 1.12) * 520, -2380, -49, 3440, width * 1.62, 0.000, color_a, ceiling_stipple_alpha * 0.82);
    screwm_draw_xy_ribbon(cos(phase * 1.08) * 520, -2140, -49, 3060, width * 1.42, 1.047, '0.86 1.00 0.72', ceiling_stipple_alpha * 0.76);
    screwm_draw_yz_wall_ribbon(1422, sin(phase * 1.21) * 1280, 700 + cos(phase * 0.93) * 118, 1720, width * 1.34, 0.000, color_c, ceiling_stipple_alpha * 0.72);
    screwm_draw_yz_wall_ribbon(1421, 1480 + cos(phase * 1.13) * 260, 650 + sin(phase * 0.97) * 130, 1180, width * 1.28, 0.720, '1.00 0.78 0.92', ceiling_stipple_alpha * 0.70);
    screwm_draw_drift_xz_wall_ribbon(2050, -1320 + sin(phase * 1.45) * 220, 540 + cos(phase * 1.09) * 118, 720, right_wall_width * 1.32, 1.570, '0.78 1.00 0.92', right_wall_alpha);
    screwm_draw_drift_xz_wall_ribbon(2049, -980 + cos(phase * 1.39) * 210, 430 + sin(phase * 1.11) * 104, 640, right_wall_width * 1.14, 0.000, '1.00 0.76 0.94', right_wall_alpha * 0.96);
    screwm_draw_drift_xz_wall_ribbon(2048, -1640 + sin(phase * 1.51) * 240, 680 + cos(phase * 0.97) * 128, 760, right_wall_width * 1.24, 1.570, '0.72 0.94 1.00', right_wall_alpha * 0.98);
    screwm_draw_drift_xz_wall_ribbon(2047, -620 + cos(phase * 1.47) * 170, 600 + sin(phase * 1.03) * 112, 520, right_wall_width, 0.000, '1.00 0.86 0.62', right_wall_alpha * 0.92);
    screwm_draw_xz_wall_ribbon(2051, -1210 + cos(phase * 1.59) * 200, 580 + sin(phase * 1.17) * 118, 560, right_wall_width * 1.12, 1.570, color_c, right_wall_alpha * 0.86);
    screwm_draw_xz_wall_ribbon(2052, -1520 + sin(phase * 1.63) * 220, 460 + cos(phase * 1.13) * 96, 500, right_wall_width, 0.000, color_b, right_wall_alpha * 0.82);

    screwm_draw_drift_xy_ribbon(-1660 + sin(phase * 0.41) * 120, -2320, 1718, 1040, width, 0.000, color_a, alpha_void);
    screwm_draw_drift_xy_ribbon(-1500 + cos(phase * 0.47) * 110, -2220, 1710, 840, width * 0.82, 1.047, '0.86 0.98 1.00', alpha_void * 0.94);
    screwm_draw_drift_xy_ribbon(-1780 + sin(phase * 0.59) * 80, -2410, 1702, 720, width * 0.74, 2.094, '0.92 1.00 0.82', alpha_void * 0.88);

    screwm_draw_drift_xy_ribbon(0, -2330, 1718, 1460, width, 0.000, color_b, alpha_ceiling);
    screwm_draw_drift_xy_ribbon(sin(phase * 0.53) * 180, -2240, 1710, 1220, width * 0.94, 1.047, color_c, alpha_ceiling * 0.94);
    screwm_draw_drift_xy_ribbon(cos(phase * 0.57) * 160, -2160, 1702, 1220, width * 0.84, 2.094, '1.00 0.86 0.62', alpha_ceiling * 0.88);
    screwm_draw_drift_xy_ribbon(1480 + cos(phase * 0.43) * 120, -2310, 1718, 1040, width * 0.92, 0.000, color_c, alpha_ceiling);
    screwm_draw_drift_xy_ribbon(1680 + sin(phase * 0.61) * 90, -2210, 1710, 840, width * 0.76, 1.047, '1.00 0.78 0.92', alpha_ceiling * 0.82);

    screwm_draw_drift_xz_wall_ribbon(1988, -2260, 540, 1080, width * 0.72, 1.570, color_a, alpha_wall);
    screwm_draw_drift_xz_wall_ribbon(1988, -2060, 470, 980, width * 0.64, 1.120, color_b, alpha_wall * 0.94);
    screwm_draw_drift_xz_wall_ribbon(1988, -1840, 610, 940, width * 0.58, 0.420, color_c, alpha_wall * 0.86);
    screwm_draw_drift_xz_wall_ribbon(1984, -2380, 330, 720, width * 0.54, 1.570, '0.86 0.96 1.00', alpha_wall * 0.82);

    screwm_draw_drift_yz_wall_ribbon(1418, -1520 + sin(phase * 0.37) * 120, 720, 1040, width * 0.62, 0.000, color_a, alpha_void * 0.86);
    screwm_draw_drift_yz_wall_ribbon(1418, 0, 760, 1380, width * 0.74, 0.000, color_b, alpha_ceiling * 0.82);
    screwm_draw_drift_yz_wall_ribbon(1418, 1480 + cos(phase * 0.39) * 120, 720, 1040, width * 0.62, 0.000, color_c, alpha_wall * 0.92);
    screwm_draw_drift_yz_wall_ribbon(1418, 1540, 520 + sin(phase * 0.67) * 90, 900, width * 0.58, 1.570, '1.00 0.78 0.92', alpha_wall * 0.84);
};

void() screwm_draw_substrate_drift_pulses =
{
    float pressure;
    float local_pressure;
    float signal;
    float phase;
    float pulse_a;
    float pulse_b;
    float pulse_c;
    float alpha_floor;
    float alpha_ceiling;
    float alpha_wall;
    float band_width;
    float entry_shift;
    vector roam_a;
    vector roam_b;
    vector roam_c;

    if (cvar("screwm_csqc_full_expression_field") <= 0)
        return;
    if (!screwm_effect_lightfield_enabled())
        return;

    pressure = screwm_effect_expression_pressure();
    local_pressure = screwm_local_effect_pressure();
    signal = screwm_clamp(
        0.28 + pressure * 0.66 + local_pressure * 0.44 + screwm_effect_drift_active_ratio * 0.62 + screwm_effect_drift_edge * 0.86 + screwm_effect_drift_texture * 0.46 + screwm_effect_drift_temporal * 0.34 + screwm_effect_drift_density_currency * 0.30,
        0.18,
        2.6
    );
    phase = time * (0.82 + screwm_effect_drift_fast_ratio * 0.34) + screwm_effect_drift_kind_variance * 5.8 + screwm_effect_drift_max_delta * 2.8;
    pulse_a = 0.50 + 0.50 * sin(phase);
    pulse_b = 0.50 + 0.50 * cos(phase * 0.71 + screwm_effect_drift_temporal * 4.0);
    pulse_c = 0.50 + 0.50 * sin(phase * 1.27 + screwm_effect_drift_density_currency * 5.0);
    alpha_floor = screwm_clamp(0.070 + signal * 0.056 + pulse_a * 0.190, 0.080, 0.48);
    alpha_ceiling = screwm_clamp(0.068 + signal * 0.054 + pulse_b * 0.184, 0.078, 0.46);
    alpha_wall = screwm_clamp(0.060 + signal * 0.048 + pulse_c * 0.160, 0.066, 0.40);
    band_width = screwm_clamp(8 + screwm_effect_drift_edge * 14 + screwm_effect_drift_texture * 10 + pulse_a * 8, 8, 28);
    entry_shift = sin(phase * 0.39) * 180;
    roam_a = screwm_synthwave_color(phase + 0.2);
    roam_b = screwm_synthwave_color(phase + 2.0);
    roam_c = screwm_synthwave_color(phase + 4.1);

    screwm_draw_xy_ribbon(0, -2260, -52, 3020, band_width, 0.000, roam_a, alpha_floor);
    screwm_draw_xy_ribbon(entry_shift, -2240, -51, 2840, band_width * 0.86, 1.047, screwm_amber, alpha_floor * 0.82);
    screwm_draw_xy_ribbon(0 - entry_shift, -2200, -50, 2840, band_width * 0.86, 2.094, screwm_green, alpha_floor * 0.80);
    screwm_draw_xy_ribbon(sin(phase * 0.62) * 460, -1580, -50, 2480, band_width * 0.72, 0.000, roam_b, alpha_floor * 0.64);
    screwm_draw_xy_ribbon(cos(phase * 0.57) * 420, -1040, -49, 2240, band_width * 0.66, 2.094, screwm_cyan, alpha_floor * 0.56);
    screwm_draw_xy_ribbon(-1600 + cos(phase * 0.74) * 240, -2380, -49, 1180, band_width * 0.70, 0.000, '0.82 0.96 0.78', screwm_clamp(alpha_floor * 1.45, 0.14, 0.72));
    screwm_draw_xy_ribbon(1600 + sin(phase * 0.76) * 240, -2380, -49, 1180, band_width * 0.70, 0.000, '1.00 0.84 0.52', screwm_clamp(alpha_floor * 1.40, 0.14, 0.70));

    screwm_draw_xy_ribbon(0, -2260, 1754, 3020, band_width, 0.000, roam_b, alpha_ceiling);
    screwm_draw_xy_ribbon(0 - entry_shift, -2180, 1753, 2840, band_width * 0.82, 1.047, screwm_cyan, alpha_ceiling * 0.82);
    screwm_draw_xy_ribbon(entry_shift, -2120, 1752, 2840, band_width * 0.82, 2.094, screwm_rose, alpha_ceiling * 0.80);
    screwm_draw_xy_ribbon(sin(phase * 0.47) * 500, -1520, 1752, 2480, band_width * 0.68, 0.000, roam_c, alpha_ceiling * 0.62);
    screwm_draw_xy_ribbon(cos(phase * 0.53) * 420, -840, 1751, 2200, band_width * 0.62, 1.047, screwm_amber, alpha_ceiling * 0.54);
    screwm_draw_xy_ribbon(-1320 + sin(phase * 0.93) * 260, -2300, 1754, 1120, band_width * 0.74, 0.000, screwm_cyan, alpha_ceiling * 1.28);
    screwm_draw_xy_ribbon(-1460 + cos(phase * 0.81) * 220, -2100, 1754, 920, band_width * 0.64, 1.047, roam_a, alpha_ceiling * 1.08);
    screwm_draw_xy_ribbon(-1820 + cos(phase * 1.03) * 180, -2410, 1754, 860, band_width * 0.70, 0.000, '0.86 0.98 1.00', screwm_clamp(alpha_ceiling * 1.86, 0.18, 0.82));
    screwm_draw_xy_ribbon(-1760 + sin(phase * 0.97) * 180, -2220, 1754, 780, band_width * 0.58, 1.047, '0.84 1.00 0.82', screwm_clamp(alpha_ceiling * 1.56, 0.16, 0.76));
    screwm_draw_xy_ribbon(1320 + cos(phase * 0.89) * 260, -2300, 1754, 1120, band_width * 0.74, 0.000, screwm_rose, alpha_ceiling * 1.24);
    screwm_draw_xy_ribbon(1460 + sin(phase * 0.77) * 220, -2100, 1754, 920, band_width * 0.64, 2.094, roam_b, alpha_ceiling * 1.04);
    screwm_draw_xy_ribbon(1820 + sin(phase * 1.01) * 180, -2410, 1754, 860, band_width * 0.70, 0.000, '1.00 0.86 0.62', screwm_clamp(alpha_ceiling * 1.74, 0.18, 0.80));

    screwm_draw_xz_wall_ribbon(2054, -1720, 420, 1680, band_width * 0.68, 1.180, screwm_rose, alpha_wall);
    screwm_draw_xz_wall_ribbon(2053, -2200, 430, 1240, band_width * 0.58, 0.420, roam_b, alpha_wall * 0.82);
    screwm_draw_xz_wall_ribbon(2052, -820, 390, 1240, band_width * 0.54, 2.120, roam_c, alpha_wall * 0.62);
    screwm_draw_xz_wall_ribbon(2051, -2260 + sin(phase * 0.83) * 260, 456 + cos(phase * 0.61) * 118, 980, band_width * 0.64, 1.620, '1.00 0.78 0.92', screwm_clamp(alpha_wall * 1.54, 0.14, 0.68));
    screwm_draw_xz_wall_ribbon(2050, -1540 + cos(phase * 0.67) * 360, 368 + sin(phase * 0.79) * 148, 1180, band_width * 0.56, 0.240, '0.86 0.96 1.00', screwm_clamp(alpha_wall * 1.24, 0.12, 0.58));
    screwm_draw_xz_wall_ribbon(-2054, -1720, 420, 1680, band_width * 0.68, 1.960, screwm_cyan, alpha_wall);
    screwm_draw_xz_wall_ribbon(-2053, -2200, 430, 1240, band_width * 0.58, 2.720, roam_a, alpha_wall * 0.82);
    screwm_draw_xz_wall_ribbon(-2052, -820, 390, 1240, band_width * 0.54, 0.960, roam_b, alpha_wall * 0.62);
    screwm_draw_xz_wall_ribbon(-2051, -2260 + cos(phase * 0.83) * 260, 456 + sin(phase * 0.61) * 118, 980, band_width * 0.64, 1.100, '0.86 0.98 1.00', screwm_clamp(alpha_wall * 1.48, 0.14, 0.66));
    screwm_draw_xz_wall_ribbon(-2050, -1540 + sin(phase * 0.67) * 360, 368 + cos(phase * 0.79) * 148, 1180, band_width * 0.56, 2.840, '0.90 1.00 0.82', screwm_clamp(alpha_wall * 1.20, 0.12, 0.56));

    screwm_draw_yz_wall_ribbon(1422, 0, 430, 2600, band_width * 0.58, 0.000, roam_c, alpha_wall * 0.72);
    screwm_draw_yz_wall_ribbon(1421, -760, 366, 1320, band_width * 0.50, 0.820, screwm_cyan, alpha_wall * 0.58);
    screwm_draw_yz_wall_ribbon(1421, 760, 366, 1320, band_width * 0.50, 2.320, screwm_rose, alpha_wall * 0.58);
    screwm_draw_entry_threshold_substrate_pulses();
};

void() screwm_add_shader_plan_lights =
{
    float plan_radius;
    float temporal_radius;

    if (!screwm_effect_lightfield_enabled())
        return;

    plan_radius = 14 + screwm_shader_plan_pass_count * 78;
    plan_radius = plan_radius + screwm_shader_plan_render_ratio * 28;
    adddynamiclight('-300 -548 386', screwm_clamp(plan_radius, 10, 142), screwm_cyan);

    adddynamiclight('-150 -548 386', screwm_clamp(12 + screwm_shader_plan_color * 112, 8, 140), screwm_amber);
    adddynamiclight('0 -548 386', screwm_clamp(12 + screwm_shader_plan_motion * 112, 8, 140), screwm_green);
    adddynamiclight('150 -548 386', screwm_clamp(12 + screwm_shader_plan_feedback * 112, 8, 140), screwm_rose);
    adddynamiclight('300 -548 386', screwm_clamp(12 + screwm_shader_plan_post * 112, 8, 140), screwm_cyan);

    temporal_radius = 12 + screwm_shader_plan_temporal_ratio * 126;
    temporal_radius = temporal_radius + screwm_reverie_temporal * 24;
    adddynamiclight('0 -548 414', screwm_clamp(temporal_radius, 8, 156), screwm_rose);
};

void() screwm_add_gem_mural_lights =
{
    float recruitment_radius;
    float frame_radius;
    float density_radius;
    float narrative_radius;

    if (!screwm_diagnostic_lightfield_enabled())
        return;

    recruitment_radius = 14 + screwm_gem_recruitment_score * 92 + screwm_gem_recruitment_fresh * 64;
    recruitment_radius = recruitment_radius + screwm_active_08 * 42 + screwm_active_11 * 28;
    adddynamiclight('-222 -360 226', screwm_clamp(recruitment_radius, 10, 170), screwm_green);
    adddynamiclight('0 -360 226', screwm_clamp(16 + screwm_gem_recruitment_score * 74 + screwm_gem_narrative_pressure * 48, 10, 156), screwm_cyan);

    frame_radius = 12 + screwm_gem_frame_count * 86 + screwm_gem_frame_fresh * 54;
    adddynamiclight('-250 -518 226', screwm_clamp(frame_radius, 8, 148), screwm_green);
    density_radius = 12 + screwm_gem_layer_density * 96 + screwm_gem_layer_opacity * 58;
    adddynamiclight('0 -518 226', screwm_clamp(density_radius, 8, 168), screwm_amber);
    narrative_radius = 12 + screwm_gem_narrative_pressure * 102 + screwm_gem_hold_pressure * 52;
    adddynamiclight('250 -518 226', screwm_clamp(narrative_radius, 8, 166), screwm_rose);
};

void() screwm_add_impingement_recruitment_lights =
{
    float impingement_radius;
    float recruitment_radius;
    float transition_radius;

    if (!screwm_diagnostic_lightfield_enabled())
        return;

    impingement_radius = 16 + screwm_impingement_count * 58 + screwm_impingement_strength * 82;
    impingement_radius = impingement_radius + screwm_impingement_fresh * 48;
    adddynamiclight('-74 -360 226', screwm_clamp(impingement_radius, 10, 174), screwm_green);
    adddynamiclight('-120 -532 276', screwm_clamp(12 + screwm_impingement_curiosity * 106 + screwm_impingement_reverie_alert * 58, 8, 168), screwm_cyan);

    recruitment_radius = 16 + screwm_recruitment_family_count * 46 + screwm_recruitment_fresh_ratio * 62;
    recruitment_radius = recruitment_radius + screwm_recruitment_score * 74;
    adddynamiclight('0 -360 226', screwm_clamp(recruitment_radius, 10, 172), screwm_cyan);
    transition_radius = 12 + screwm_recruitment_transition_pressure * 98 + screwm_recruitment_studio_pressure * 66;
    adddynamiclight('120 -532 276', screwm_clamp(transition_radius, 8, 176), screwm_amber);
};

void() screwm_add_programme_segment_lights =
{
    float banner_radius;
    float state_radius;
    float segment_radius;
    float grounding_radius;

    if (!screwm_diagnostic_lightfield_enabled())
        return;

    banner_radius = 16 + screwm_programme_role * 72 + screwm_programme_cue_hold * 64;
    banner_radius = banner_radius + screwm_active_21 * 36;
    adddynamiclight('222 -360 172', screwm_clamp(banner_radius, 10, 158), screwm_amber);

    state_radius = 14 + screwm_programme_beat_progress * 96 + screwm_programme_beat_index * 42;
    state_radius = state_radius + screwm_programme_duration_pressure * 34;
    adddynamiclight('222 -360 118', screwm_clamp(state_radius, 10, 174), screwm_amber);

    segment_radius = 14 + screwm_programme_source_pressure * 78 + screwm_programme_asset_pressure * 74;
    segment_radius = segment_radius + screwm_programme_affordance_pressure * 48;
    adddynamiclight('148 -360 64', screwm_clamp(segment_radius, 10, 178), screwm_green);

    grounding_radius = 12 + screwm_programme_source_pressure * 88 + screwm_programme_asset_pressure * 72;
    adddynamiclight('0 -536 330', screwm_clamp(grounding_radius, 8, 176), screwm_cyan);
};

void() screwm_add_live_context_lights =
{
    float token_radius;
    float album_radius;
    float voice_radius;

    if (!screwm_diagnostic_lightfield_enabled())
        return;

    token_radius = 14 + screwm_live_token_pressure * 88 + screwm_live_token_burst * 54;
    token_radius = token_radius + screwm_live_viewer_pressure * 38;
    adddynamiclight('-222 -360 280', screwm_clamp(token_radius, 10, 172), screwm_cyan);

    album_radius = 14 + screwm_live_album_confidence * 82 + screwm_live_album_fresh * 44;
    album_radius = album_radius + screwm_live_album_playing * 54 + screwm_live_album_risk * 32;
    adddynamiclight('-148 -360 280', screwm_clamp(album_radius, 10, 174), screwm_rose);

    voice_radius = 12 + screwm_live_voice_active * 104 + screwm_voice * 48 + screwm_audio_onset * 36;
    adddynamiclight('74 -360 226', screwm_clamp(voice_radius, 8, 172), screwm_amber);
    adddynamiclight('-222 -360 172', screwm_clamp(10 + screwm_live_viewer_pressure * 82, 8, 120), screwm_amber);
};

void() screwm_add_governance_health_lights =
{
    float consent_radius;
    float health_radius;
    float follow_radius;

    if (!screwm_diagnostic_lightfield_enabled())
        return;

    consent_radius = 14 + screwm_governance_consent_allowed * 82 + screwm_governance_persistence_allowed * 42;
    adddynamiclight('-300 -548 460', screwm_clamp(consent_radius, 8, 156), screwm_green);

    health_radius = 14 + screwm_governance_health_reference * 58 + screwm_governance_health_perception * 58;
    health_radius = health_radius + screwm_governance_health_fresh * 34 - screwm_governance_health_error * 48;
    adddynamiclight('0 -548 460', screwm_clamp(health_radius, 8, 170), screwm_cyan);
    adddynamiclight('-74 -360 118', screwm_clamp(12 + screwm_governance_health_error * 112, 8, 156), screwm_rose);

    follow_radius = 12 + screwm_governance_follow_active * 74 + screwm_governance_follow_confidence * 64;
    follow_radius = follow_radius + screwm_governance_follow_fresh * 36;
    adddynamiclight('300 -548 460', screwm_clamp(follow_radius, 8, 168), screwm_amber);
};

void(float slot, vector base, vector sweep, float phase_offset) screwm_add_theatre_spot =
{
    vector color;
    vector top;
    vector mid;
    vector foot;
    float phase;
    float slow_a;
    float slow_b;
    float radius;

    phase = time * 0.055 + phase_offset + screwm_effect_drift_kind_variance * 1.2;
    slow_a = sin(time * (0.043 + slot * 0.007) + phase_offset);
    slow_b = sin(time * (0.029 + slot * 0.011) + phase_offset * 1.7);
    color = screwm_synthwave_color(phase);

    top = base;
    top_x = top_x + sweep_x * slow_a;
    top_y = top_y + sweep_y * slow_b;
    top_z = top_z + sweep_z * sin(time * 0.021 + phase_offset);

    mid = top;
    mid_x = mid_x * 0.70;
    mid_y = mid_y * 0.66 + -650 * 0.34;
    mid_z = mid_z - 190;

    foot = mid;
    foot_x = foot_x * 0.50;
    foot_y = foot_y - 360;
    foot_z = 72 + 32 * sin(time * 0.037 + phase_offset);

    radius = 34 + screwm_effect_drift_active_ratio * 18 + screwm_chain_color * 16;
    radius = radius + screwm_effect_drift_kind_variance * 18;
    adddynamiclight(top, screwm_clamp(radius * 0.24, 8, 24), color * 0.18);
    adddynamiclight(mid, screwm_clamp(radius * 0.72, 24, 58), color * 0.54);
    adddynamiclight(foot, screwm_clamp(radius * 0.22, 6, 22), color * 0.16);
};

void() screwm_draw_ward_links =
{
    vector c01;
    vector c02;
    vector c03;
    vector c04;
    vector c05;

    c01 = '0 -360 280';
    c02 = '0 -360 226';
    c03 = '0 -360 172';
    c04 = '0 -360 118';
    c05 = '0 -360 64';

    screwm_draw_link('-222 -360 280', '-148 -360 226', 0.0, screwm_cyan);
    screwm_draw_link('-148 -360 280', '-74 -360 226', 0.6, screwm_amber);
    screwm_draw_link('-74 -360 280', c02, 1.2, screwm_rose);
    screwm_draw_link(c01, '74 -360 226', 1.8, screwm_green);
    screwm_draw_link('74 -360 280', '148 -360 226', 2.4, screwm_cyan);
    screwm_draw_link('148 -360 280', '222 -360 226', 3.0, screwm_amber);

    screwm_draw_link('-222 -360 172', '-148 -360 118', 3.6, screwm_green);
    screwm_draw_link('-74 -360 172', c04, 4.2, screwm_cyan);
    screwm_draw_link(c03, '74 -360 118', 4.8, screwm_rose);
    screwm_draw_link('148 -360 172', '222 -360 118', 5.4, screwm_amber);

    screwm_draw_link(c01, c03, 6.0, screwm_cyan);
    screwm_draw_link(c03, c05, 6.6, screwm_green);
    screwm_draw_link('-222 -360 64', '222 -360 64', 7.2, screwm_rose);
    screwm_draw_link('0 -360 118', '0 -360 28', 7.8, screwm_rose);
    screwm_draw_link('0 -360 64', '0 -360 28', 8.4, screwm_cyan);
};

void() screwm_draw_wards =
{
    screwm_draw_ward_links();

    screwm_draw_ward_label('-222 -360 280', "01", "TOKEN", 1, screwm_cyan);
    screwm_draw_ward_label('-148 -360 280', "02", "ALBUM", 2, screwm_rose);
    screwm_draw_ward_label('-74 -360 280', "03", "STREAM", 3, screwm_green);
    screwm_draw_ward_label('0 -360 280', "04", "SIERP", 4, screwm_green);
    screwm_draw_ward_label('74 -360 280', "05", "REVERIE", 5, screwm_green);
    screwm_draw_ward_label('148 -360 280', "06", "ACT", 6, screwm_cyan);
    screwm_draw_ward_label('222 -360 280', "07", "STANCE", 7, screwm_amber);

    screwm_draw_ward_label('-222 -360 226', "08", "GEM", 8, screwm_green);
    screwm_draw_ward_label('-148 -360 226', "09", "GROUND", 9, screwm_amber);
    screwm_draw_ward_label('-74 -360 226', "10", "IMPINGE", 10, screwm_green);
    screwm_draw_ward_label('0 -360 226', "11", "RECRUIT", 11, screwm_cyan);
    screwm_draw_ward_label('74 -360 226', "12", "THINK", 12, screwm_amber);
    screwm_draw_ward_label('148 -360 226', "13", "PRESS", 13, screwm_amber);
    screwm_draw_ward_label('222 -360 226', "14", "VARIETY", 14, screwm_cyan);

    screwm_draw_ward_label('-222 -360 172', "15", "HERE", 15, screwm_amber);
    screwm_draw_ward_label('-148 -360 172', "16", "DURF", 16, screwm_green);
    screwm_draw_ward_label('-74 -360 172', "17", "CODE", 17, screwm_cyan);
    screwm_draw_ward_label('0 -360 172', "18", "M8", 18, screwm_rose);
    screwm_draw_ward_label('74 -360 172', "19", "DECK", 19, screwm_rose);
    screwm_draw_ward_label('148 -360 172', "20", "EGRESS", 20, screwm_amber);
    screwm_draw_ward_label('222 -360 172', "21", "BANNER", 21, screwm_amber);

    screwm_draw_ward_label('-222 -360 118', "22", "PRECED", 22, screwm_amber);
    screwm_draw_ward_label('-148 -360 118', "23", "HISTORY", 23, screwm_cyan);
    screwm_draw_ward_label('-74 -360 118', "24", "INSTR", 24, screwm_cyan);
    screwm_draw_ward_label('0 -360 118', "25", "CBIP", 25, screwm_green);
    screwm_draw_ward_label('74 -360 118', "26", "CHAT", 26, screwm_green);
    screwm_draw_ward_label('148 -360 118', "27", "CHRON", 27, screwm_amber);
    screwm_draw_ward_label('222 -360 118', "28", "STATE", 28, screwm_amber);

    screwm_draw_ward_label('-222 -360 64', "29", "POLYEND", 29, screwm_rose);
    screwm_draw_ward_label('-148 -360 64', "30", "QUERY", 30, screwm_cyan);
    screwm_draw_ward_label('-74 -360 64', "31", "POSTER", 31, screwm_cyan);
    screwm_draw_ward_label('0 -360 64', "32", "TUFTE", 32, screwm_cyan);
    screwm_draw_ward_label('74 -360 64', "33", "ASCII", 33, screwm_cyan);
    screwm_draw_ward_label('148 -360 64', "34", "SEGMENT", 34, screwm_green);
    screwm_draw_ward_label('222 -360 64', "35", "SCOPE", 35, screwm_rose);
    screwm_draw_ward_label('0 -360 28', "36", "IRDUAL", 36, screwm_green);

    screwm_draw_ward_detail('-222 -360 280', screwm_w01, 1, screwm_cyan);
    screwm_draw_ward_detail('-148 -360 280', screwm_w02, 2, screwm_rose);
    screwm_draw_ward_detail('-74 -360 280', screwm_w03, 3, screwm_green);
    screwm_draw_ward_detail('0 -360 280', screwm_w04, 4, screwm_green);
    screwm_draw_ward_detail('74 -360 280', screwm_w05, 5, screwm_green);
    screwm_draw_ward_detail('148 -360 280', screwm_w06, 6, screwm_cyan);
    screwm_draw_ward_detail('222 -360 280', screwm_w07, 7, screwm_amber);
    screwm_draw_ward_detail('-222 -360 226', screwm_w08, 8, screwm_green);
    screwm_draw_ward_detail('-148 -360 226', screwm_w09, 9, screwm_amber);
    screwm_draw_ward_detail('-74 -360 226', screwm_w10, 10, screwm_green);
    screwm_draw_ward_detail('0 -360 226', screwm_w11, 11, screwm_cyan);
    screwm_draw_ward_detail('74 -360 226', screwm_w12, 12, screwm_amber);
    screwm_draw_ward_detail('148 -360 226', screwm_w13, 13, screwm_amber);
    screwm_draw_ward_detail('222 -360 226', screwm_w14, 14, screwm_cyan);
    screwm_draw_ward_detail('-222 -360 172', screwm_w15, 15, screwm_amber);
    screwm_draw_ward_detail('-148 -360 172', screwm_w16, 16, screwm_green);
    screwm_draw_ward_detail('-74 -360 172', screwm_w17, 17, screwm_cyan);
    screwm_draw_ward_detail('0 -360 172', screwm_w18, 18, screwm_rose);
    screwm_draw_ward_detail('74 -360 172', screwm_w19, 19, screwm_rose);
    screwm_draw_ward_detail('148 -360 172', screwm_w20, 20, screwm_amber);
    screwm_draw_ward_detail('222 -360 172', screwm_w21, 21, screwm_amber);
    screwm_draw_ward_detail('-222 -360 118', screwm_w22, 22, screwm_amber);
    screwm_draw_ward_detail('-148 -360 118', screwm_w23, 23, screwm_cyan);
    screwm_draw_ward_detail('-74 -360 118', screwm_w24, 24, screwm_cyan);
    screwm_draw_ward_detail('0 -360 118', screwm_w25, 25, screwm_green);
    screwm_draw_ward_detail('74 -360 118', screwm_w26, 26, screwm_green);
    screwm_draw_ward_detail('148 -360 118', screwm_w27, 27, screwm_amber);
    screwm_draw_ward_detail('222 -360 118', screwm_w28, 28, screwm_amber);
    screwm_draw_ward_detail('-222 -360 64', screwm_w29, 29, screwm_rose);
    screwm_draw_ward_detail('-148 -360 64', screwm_w30, 30, screwm_cyan);
    screwm_draw_ward_detail('-74 -360 64', screwm_w31, 31, screwm_cyan);
    screwm_draw_ward_detail('0 -360 64', screwm_w32, 32, screwm_cyan);
    screwm_draw_ward_detail('74 -360 64', screwm_w33, 33, screwm_cyan);
    screwm_draw_ward_detail('148 -360 64', screwm_w34, 34, screwm_green);
    screwm_draw_ward_detail('222 -360 64', screwm_w35, 35, screwm_rose);
    screwm_draw_ward_detail('0 -360 28', screwm_w36, 36, screwm_green);
};

void() screwm_draw_header =
{
    string mode_line;
    string energy_line;
    float alpha;

    alpha = 0.44 + screwm_energy * 0.18;
    mode_line = strcat("SCREWM FIELD / DARKPLACES SUBSTRATE / ", screwm_mode);
    energy_line = strcat("WARD ANCHORS 36 / DRIFT ", ftos(screwm_energy));

    drawfill('18 18 0', '420 34 0', '0.02 0.03 0.03', 0.22, DRAWFLAG_NORMAL);
    drawstring('26 24 0', mode_line, '7 7 0', screwm_cyan, alpha, DRAWFLAG_ADDITIVE);
    drawstring('26 38 0', energy_line, '5 5 0', screwm_amber, alpha * 0.80, DRAWFLAG_ADDITIVE);
};

void() screwm_add_dynamic_lights =
{
    float pulse;
    float voice_radius;

    if (cvar("screwm_csqc_disable") > 0)
        return;
    if (cvar("screwm_csqc_lightfield") < 0)
        return;
    if (screwm_shadow_budget_enabled())
    {
        screwm_add_shadow_budget_lights();
        return;
    }

    pulse = 82 + screwm_energy * 38 + screwm_audio_rms * 24;
    voice_radius = 12 + screwm_voice * 28 + screwm_audio_onset * 18;

    adddynamiclight('0 -555 224', pulse + voice_radius, '0.70 0.36 0.16');
    if (cvar("screwm_review_fill_light") > 0)
        adddynamiclight('0 -555 250', 92 + screwm_energy * 34, '0.36 0.28 0.24');
    adddynamiclight('-420 -870 210', 42 + screwm_energy * 22, screwm_cyan * 0.55);
    adddynamiclight('420 -760 200', 42 + screwm_voice * 28, screwm_rose * 0.55);
    adddynamiclight('0 -555 385', 34 + screwm_energy * 18, screwm_green * 0.50);
    adddynamiclight('0 -1240 205', 34 + screwm_voice * 26, screwm_amber * 0.48);
    // Floor wash: the world floor shell is a hidden carrier, so light must read
    // on generated hex/stipple geometry and ward-bound receivers.
    adddynamiclight('0 -555 -32', 110 + screwm_energy * 42 + screwm_audio_rms * 28, '0.70 0.56 0.34');
    if (cvar("screwm_csqc_theatre_spots") > 0)
    {
        screwm_add_theatre_spot(1, '-720 -1880 700', '360 520 70', 0.3);
        screwm_add_theatre_spot(2, '760 -880 680', '-420 460 90', 3.1);
    }
    screwm_add_homage_lights();
    screwm_add_material_field_lights();
    screwm_add_visual_layer_lights();
    screwm_add_visual_chain_lights();
    screwm_add_scroom_baseline_lights();
    screwm_add_aoa_drift_lights();
    screwm_add_hex_grid_drift_lights();
    screwm_add_expression_surface_lights();
    screwm_add_entry_substrate_drift_lights();
    screwm_add_world_edge_lattice_lights();
    screwm_add_imagination_intent_lights();
    screwm_add_local_effect_lights();
    screwm_add_shader_plan_lights();
    screwm_add_gem_mural_lights();
    screwm_add_impingement_recruitment_lights();
    screwm_add_programme_segment_lights();
    screwm_add_live_context_lights();
    screwm_add_governance_health_lights();
    screwm_add_ward_property_field_lights();

    screwm_add_ward_light('-900 -2360 130', 1, screwm_cyan, screwm_active_01, screwm_presence_01);
    screwm_add_ward_light('-1180 -1780 150', 2, screwm_rose, screwm_active_02, screwm_presence_02);
    screwm_add_ward_light('-1040 980 300', 3, screwm_green, screwm_active_03, screwm_presence_03);
    screwm_add_ward_light('-1180 -1540 245', 4, screwm_green, screwm_active_04, screwm_presence_04);
    screwm_add_ward_light('-700 -1120 260', 5, screwm_green, screwm_active_05, screwm_presence_05);
    screwm_add_ward_light('1180 -1780 315', 6, screwm_cyan, screwm_active_06, screwm_presence_06);
    screwm_add_ward_light('-640 980 190', 7, screwm_amber, screwm_active_07, screwm_presence_07);
    screwm_add_ward_light('-1180 -760 260', 8, screwm_green, screwm_active_08, screwm_presence_08);
    screwm_add_ward_light('-1580 -1860 220', 9, screwm_amber, screwm_active_09, screwm_presence_09);
    screwm_add_ward_light('-260 980 330', 10, screwm_green, screwm_active_10, screwm_presence_10);
    screwm_add_ward_light('1180 -1540 230', 11, screwm_cyan, screwm_active_11, screwm_presence_11);
    screwm_add_ward_light('80 980 215', 12, screwm_amber, screwm_active_12, screwm_presence_12);
    screwm_add_ward_light('420 980 140', 13, screwm_amber, screwm_active_13, screwm_presence_13);
    screwm_add_ward_light('1180 -980 165', 14, screwm_cyan, screwm_active_14, screwm_presence_14);
    screwm_add_ward_light('800 980 285', 15, screwm_amber, screwm_active_15, screwm_presence_15);
    screwm_add_ward_light('-1180 -420 150', 16, screwm_green, screwm_active_16, screwm_presence_16);
    screwm_add_ward_light('1180 -760 290', 17, screwm_cyan, screwm_active_17, screwm_presence_17);
    screwm_add_ward_light('-1180 -150 250', 18, screwm_rose, screwm_active_18, screwm_presence_18);
    screwm_add_ward_light('-1180 -2020 310', 19, screwm_rose, screwm_active_19, screwm_presence_19);
    screwm_add_ward_light('520 -2360 105', 20, screwm_amber, screwm_active_20, screwm_presence_20);
    screwm_add_ward_light('1160 980 340', 21, screwm_amber, screwm_active_21, screwm_presence_21);
    screwm_add_ward_light('1580 -1860 220', 22, screwm_amber, screwm_active_22, screwm_presence_22);
    screwm_add_ward_light('1180 -420 160', 23, screwm_cyan, screwm_active_23, screwm_presence_23);
    screwm_add_ward_light('1180 -150 300', 24, screwm_cyan, screwm_active_24, screwm_presence_24);
    screwm_add_ward_light('-1180 -1180 350', 25, screwm_green, screwm_active_25, screwm_presence_25);
    screwm_add_ward_light('-1040 980 140', 26, screwm_green, screwm_active_26, screwm_presence_26);
    screwm_add_ward_light('-1580 -980 360', 27, screwm_amber, screwm_active_27, screwm_presence_27);
    screwm_add_ward_light('-80 980 120', 28, screwm_amber, screwm_active_28, screwm_presence_28);
    screwm_add_ward_light('-1180 120 345', 29, screwm_rose, screwm_active_29, screwm_presence_29);
    screwm_add_ward_light('1180 -2020 115', 30, screwm_cyan, screwm_active_30, screwm_presence_30);
    screwm_add_ward_light('1180 -1240 300', 31, screwm_cyan, screwm_active_31, screwm_presence_31);
    screwm_add_ward_light('1180 -580 110', 32, screwm_cyan, screwm_active_32, screwm_presence_32);
    screwm_add_ward_light('1180 -280 330', 33, screwm_cyan, screwm_active_33, screwm_presence_33);
    screwm_add_ward_light('1160 980 210', 34, screwm_green, screwm_active_34, screwm_presence_34);
    screwm_add_ward_light('-1180 -1320 330', 35, screwm_rose, screwm_active_35, screwm_presence_35);
    screwm_add_ward_light('-1180 -600 330', 36, screwm_green, screwm_active_36, screwm_presence_36);

    screwm_add_drift_light('-1240 -2110 175', 1, screwm_cyan, screwm_active_01, screwm_active_09);
    screwm_add_drift_light('-720 -400 240', 2, screwm_amber, screwm_active_02, screwm_active_10);
    screwm_add_drift_light('70 -280 265', 3, screwm_rose, screwm_active_03, screwm_active_11);
    screwm_add_drift_light('-550 -280 230', 4, screwm_green, screwm_active_04, screwm_active_12);
    screwm_add_drift_light('-140 -70 200', 5, screwm_cyan, screwm_active_05, screwm_active_13);
    screwm_add_drift_light('1180 -1380 240', 6, screwm_amber, screwm_active_06, screwm_active_14);
    screwm_add_drift_light('80 980 237', 7, screwm_amber, screwm_active_07, screwm_active_15);
    screwm_add_drift_light('-1180 -590 205', 8, screwm_green, screwm_active_08, screwm_active_16);
    screwm_add_drift_light('990 280 222', 9, screwm_green, screwm_active_15, screwm_active_23);
    screwm_add_drift_light('0 -285 225', 10, screwm_cyan, screwm_active_16, screwm_active_24);
    screwm_add_drift_light('0 -970 320', 11, screwm_cyan, screwm_active_17, screwm_active_25);
    screwm_add_drift_light('-1110 415 195', 12, screwm_rose, screwm_active_18, screwm_active_26);
    screwm_add_drift_light('-1380 -1500 335', 13, screwm_rose, screwm_active_19, screwm_active_27);
    screwm_add_drift_light('220 -690 112', 14, screwm_amber, screwm_active_20, screwm_active_28);
    screwm_add_drift_light('540 980 230', 15, screwm_amber, screwm_active_21, screwm_active_28);
    screwm_add_drift_light('1380 -1940 167', 16, screwm_amber, screwm_active_22, screwm_active_30);
    screwm_add_drift_light('1180 -695 300', 17, screwm_cyan, screwm_active_24, screwm_active_31);
    screwm_add_drift_light('-210 0 285', 18, screwm_amber, screwm_active_27, screwm_active_34);
    screwm_add_drift_light('-1180 -845 247', 19, screwm_cyan, screwm_active_04, screwm_active_18);
    screwm_add_drift_light('0 -365 180', 20, screwm_green, screwm_active_18, screwm_active_32);
    screwm_add_drift_light('-1180 -600 337', 21, screwm_rose, screwm_active_29, screwm_active_35);
    screwm_add_drift_light('1180 -1150 222', 22, screwm_cyan, screwm_active_30, screwm_active_33);
    screwm_add_drift_light('1170 -130 255', 23, screwm_cyan, screwm_active_31, screwm_active_34);
    screwm_add_drift_light('0 -440 330', 24, screwm_cyan, screwm_active_33, screwm_active_36);
    screwm_add_drift_light('-10 190 270', 25, screwm_green, screwm_active_34, screwm_active_36);
    screwm_add_drift_light('-1180 -890 340', 26, screwm_rose, screwm_active_25, screwm_active_36);
    screwm_add_drift_light('0 -590 220', 27, screwm_cyan, screwm_active_32, screwm_active_36);

    screwm_add_media_source_signal_lights();
    screwm_add_aoa_pane_signal_lights();

    screwm_add_scene_graph_light('-1580 -2170 290', 1, screwm_amber, screwm_source_priority_01, screwm_source_fresh_01);
    screwm_add_scene_graph_light('-1580 -1350 190', 2, screwm_green, screwm_source_priority_02, screwm_source_fresh_02);
    screwm_add_scene_graph_light('-1580 -530 300', 3, screwm_rose, screwm_source_priority_03, screwm_source_fresh_03);
    screwm_add_scene_graph_light('1580 -2170 290', 4, screwm_cyan, screwm_source_priority_04, screwm_source_fresh_04);
    screwm_add_scene_graph_light('1580 -1350 190', 5, screwm_green, screwm_source_priority_05, screwm_source_fresh_05);
    screwm_add_scene_graph_light('1580 -530 300', 6, screwm_green, screwm_source_priority_06, screwm_source_fresh_06);
    screwm_add_scene_graph_light('-1180 -630 330', 7, screwm_cyan, screwm_active_36, screwm_active_36);
    screwm_add_scene_graph_light('1180 -450 160', 8, screwm_amber, screwm_active_23, screwm_active_23);
    screwm_add_scene_graph_light('1180 -180 300', 9, screwm_amber, screwm_active_24, screwm_active_24);
    screwm_add_scene_graph_light('1180 -2050 115', 10, screwm_amber, screwm_active_30, screwm_active_30);
    screwm_add_scene_graph_light('-1040 980 140', 11, screwm_green, screwm_active_26, screwm_active_26);
    screwm_add_scene_graph_light('-260 980 330', 12, screwm_green, screwm_active_10, screwm_active_10);
    screwm_add_scene_graph_light('1180 -1010 165', 13, screwm_cyan, screwm_active_14, screwm_active_14);
    screwm_add_scene_graph_light('-1180 -1350 330', 14, screwm_cyan, screwm_active_35, screwm_active_35);
};

void(float apilevel, string enginename, float engineversion) CSQC_Init =
{
    screwm_energy = 0.5;
    screwm_voice = 0;
    screwm_mode = "rnd";
    screwm_next_poll = 0;
    screwm_review_camera_origin = '0 -2360 190';
    screwm_review_camera_angles = vectoangles('0 -555 254' - screwm_review_camera_origin);
    screwm_review_camera_angles_z = 0;
    screwm_review_camera_fov = '92 57.5 0';
    screwm_review_camera_period = 360.0;
    screwm_review_camera_two_pi = 6.283185;
    precache_pic("geom_mark");
    precache_pic("drift_c");
};

void() CSQC_Shutdown =
{
};

float(float evtype, float scanx, float chary) CSQC_InputEvent =
{
    return FALSE;
};

float(string cmdstr) CSQC_ConsoleCommand =
{
    return FALSE;
};

void(float vid_width, float vid_height, float notmenu) CSQC_UpdateView =
{
    screwm_width = vid_width;
    screwm_height = vid_height;
    screwm_poll_state();

    clearscene();
    screwm_apply_review_camera();
    setproperty(VF_DRAWWORLD, TRUE);
    setproperty(VF_DRAWENGINESBAR, FALSE);
    setproperty(VF_DRAWCROSSHAIR, FALSE);
    addentities(MASK_ENGINE | MASK_NORMAL);
    screwm_add_dynamic_lights();
    if (screwm_surface_grid_overlay_enabled())
        screwm_draw_hex_alignment_light_grid();
    if (screwm_roaming_surface_pulses_enabled())
    {
        screwm_draw_media_receiver_drift_fields();
        screwm_draw_geometry_edge_pulses();
        screwm_draw_substrate_drift_pulses();
    }
    renderscene();

    if (cvar("screwm_csqc_overlay") > 0 && cvar("screwm_csqc_disable") <= 0)
    {
        screwm_draw_wards();
        screwm_draw_header();
    }
};
