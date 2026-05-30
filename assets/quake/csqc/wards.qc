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

vector screwm_cyan = '0.45 0.95 0.88';
vector screwm_amber = '1.00 0.62 0.23';
vector screwm_rose = '1.00 0.35 0.55';
vector screwm_green = '0.55 0.85 0.42';
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

float(float value) screwm_abs =
{
    if (value < 0)
        return 0 - value;
    return value;
};

vector(float phase) screwm_synthwave_color =
{
    vector color;

    color = '0 0 0';
    color_x = screwm_clamp(0.48 + 0.34 * sin(phase), 0.08, 0.86);
    color_y = screwm_clamp(0.26 + 0.24 * sin(phase + 2.094), 0.06, 0.58);
    color_z = screwm_clamp(0.60 + 0.36 * sin(phase + 4.188), 0.22, 0.98);
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
        screwm_review_camera_origin_z = screwm_clamp(screwm_review_camera_origin_z, -48, 780);
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
        cycle = time * 800 / screwm_review_camera_period;
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
            target_a = '0 -555 206';
            target_b = '0 -555 210';
        }
        else if (cycle < 200)
        {
            u = (cycle - 100) / 100;
            origin_a = '-240 -2200 204';
            origin_b = '-560 -1880 218';
            target_a = '0 -555 210';
            target_b = '0 -555 214';
        }
        else if (cycle < 300)
        {
            u = (cycle - 200) / 100;
            origin_a = '-560 -1880 218';
            origin_b = '-720 -1460 230';
            target_a = '0 -555 214';
            target_b = '0 -555 214';
        }
        else if (cycle < 400)
        {
            u = (cycle - 300) / 100;
            origin_a = '-720 -1460 230';
            origin_b = '-520 -1120 224';
            target_a = '0 -555 214';
            target_b = '0 -555 214';
        }
        else if (cycle < 500)
        {
            u = (cycle - 400) / 100;
            origin_a = '-520 -1120 224';
            origin_b = '520 -1120 224';
            target_a = '0 -555 214';
            target_b = '0 -555 214';
        }
        else if (cycle < 600)
        {
            u = (cycle - 500) / 100;
            origin_a = '520 -1120 224';
            origin_b = '720 -1460 230';
            target_a = '0 -555 214';
            target_b = '0 -555 214';
        }
        else if (cycle < 700)
        {
            u = (cycle - 600) / 100;
            origin_a = '720 -1460 230';
            origin_b = '560 -1880 218';
            target_a = '0 -555 214';
            target_b = '0 -555 214';
        }
        else
        {
            u = (cycle - 700) / 100;
            origin_a = '560 -1880 218';
            origin_b = '0 -2360 190';
            target_a = '0 -555 214';
            target_b = '0 -555 206';
        }

        s = u * u * (3 - 2 * u);
        phase = time * screwm_review_camera_two_pi / screwm_review_camera_period;
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

    alpha = 0.50 + 0.18 * sin(time * 1.7 + idx * 0.43);
    if (screwm_voice > 0)
        alpha = alpha + 0.12;
    alpha = screwm_clamp(alpha, 0.30, 0.82);

    code_pos = p + '-16 -8 0';
    label_pos = p + '8 -6 0';
    drawfill(p + '-20 -11 0', '62 14 0', screwm_dim, 0.28, DRAWFLAG_NORMAL);
    drawstring(code_pos, ordinal, '7 7 0', color, alpha, DRAWFLAG_ADDITIVE);
    drawstring(label_pos, label, '5 5 0', color, alpha * 0.74, DRAWFLAG_ADDITIVE);
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

    alpha = 0.34 + 0.14 * sin(time * 1.1 + idx * 0.31);
    drawfill(p + '-34 8 0', '92 11 0', screwm_dim, 0.24, DRAWFLAG_NORMAL);
    drawstring(p + '-31 10 0', text, '4 4 0', color, screwm_clamp(alpha, 0.18, 0.56), DRAWFLAG_ADDITIVE);
};

float() screwm_diagnostic_lightfield_enabled =
{
    return cvar("screwm_csqc_diagnostic_lightfield") > 0;
};

float() screwm_effect_lightfield_enabled =
{
    return cvar("screwm_csqc_effect_lightfield") > 0 || screwm_diagnostic_lightfield_enabled();
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

void(vector org, float idx, vector color, float signal) screwm_add_local_effect_light =
{
    float radius;

    if (!screwm_effect_lightfield_enabled())
        return;

    radius = 12 + screwm_energy * 16 + signal * 104;
    radius = radius + screwm_effect_drift_active_effect_ratio * 28 + screwm_effect_drift_kind_variance * 18;
    radius = radius + screwm_reverie_temporal * 16 + screwm_reverie_material * 18;
    radius = radius + screwm_audio_onset * 20 + screwm_homage_signature * 14;
    adddynamiclight(org, screwm_clamp(radius, 8, 128), color);
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

    screwm_add_local_effect_light('-250 -546 28', 1, screwm_cyan, screwm_effect_01);
    screwm_add_local_effect_light('-200 -546 28', 2, screwm_rose, screwm_effect_02);
    screwm_add_local_effect_light('-150 -546 28', 3, screwm_green, screwm_effect_03);
    screwm_add_local_effect_light('-100 -546 28', 4, screwm_cyan, screwm_effect_04);
    screwm_add_local_effect_light('-50 -546 28', 5, screwm_amber, screwm_effect_05);
    screwm_add_local_effect_light('0 -546 28', 6, screwm_rose, screwm_effect_06);
    screwm_add_local_effect_light('50 -546 28', 7, screwm_cyan, screwm_effect_07);
    screwm_add_local_effect_light('100 -546 28', 8, screwm_green, screwm_effect_08);
    screwm_add_local_effect_light('150 -546 28', 9, screwm_amber, screwm_effect_09);
    screwm_add_local_effect_light('200 -546 28', 10, screwm_green, screwm_effect_10);
    screwm_add_local_effect_light('250 -546 28', 11, screwm_amber, screwm_effect_11);
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

    pulse = 82 + screwm_energy * 38 + screwm_audio_rms * 24;
    voice_radius = 12 + screwm_voice * 28 + screwm_audio_onset * 18;

    adddynamiclight('0 -555 176', pulse + voice_radius, '0.70 0.36 0.16');
    if (cvar("screwm_review_fill_light") > 0)
        adddynamiclight('0 -555 196', 92 + screwm_energy * 34, '0.36 0.28 0.24');
    adddynamiclight('-420 -870 210', 42 + screwm_energy * 22, screwm_cyan * 0.55);
    adddynamiclight('420 -760 200', 42 + screwm_voice * 28, screwm_rose * 0.55);
    adddynamiclight('0 -555 300', 34 + screwm_energy * 18, screwm_green * 0.50);
    adddynamiclight('0 -1240 205', 34 + screwm_voice * 26, screwm_amber * 0.48);
    // Floor wash: the world floor had no floor-aimed light, so cmp_floor stayed
    // below the signal_presence gate while walls transformed. Grounds the scene
    // and lifts the floor into the drift band; audio-reactive like the others.
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

    screwm_add_aoa_pane_light('-4 -597 284', 1, screwm_cyan, screwm_aoa_pane_01);
    screwm_add_aoa_pane_light('-72 -597 238', 2, screwm_green, screwm_aoa_pane_02);
    screwm_add_aoa_pane_light('72 -597 238', 3, screwm_amber, screwm_aoa_pane_03);
    screwm_add_aoa_pane_light('-118 -597 170', 4, screwm_rose, screwm_aoa_pane_04);
    screwm_add_aoa_pane_light('118 -597 170', 5, screwm_cyan, screwm_aoa_pane_05);
    screwm_add_aoa_pane_light('-76 -597 102', 6, screwm_green, screwm_aoa_pane_06);
    screwm_add_aoa_pane_light('76 -597 102', 7, screwm_amber, screwm_aoa_pane_07);
    screwm_add_aoa_pane_light('-176 -597 216', 8, screwm_rose, screwm_aoa_pane_08);
    screwm_add_aoa_pane_light('176 -597 216', 9, screwm_cyan, screwm_aoa_pane_09);
    screwm_add_aoa_pane_light('0 -597 64', 10, screwm_green, screwm_aoa_pane_10);

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
    screwm_review_camera_angles = vectoangles('0 -555 206' - screwm_review_camera_origin);
    screwm_review_camera_angles_z = 0;
    screwm_review_camera_fov = '92 57.5 0';
    screwm_review_camera_period = 360.0;
    screwm_review_camera_two_pi = 6.283185;
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
    renderscene();

    if (cvar("screwm_csqc_overlay") > 0 && cvar("screwm_csqc_disable") <= 0)
    {
        screwm_draw_wards();
        screwm_draw_header();
    }
};
