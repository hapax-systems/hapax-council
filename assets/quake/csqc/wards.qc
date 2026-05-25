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
};

void() screwm_apply_review_camera =
{
    float phase;
    float lift_phase;
    float manual;
    float fov;
    float native_delta;
    float native_move;
    float native_hold;
    float native_speed;
    vector angle_delta;

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
        screwm_review_camera_origin_x = screwm_clamp(screwm_review_camera_origin_x, -360, 360);
        screwm_review_camera_origin_y = screwm_clamp(screwm_review_camera_origin_y, -720, 40);
        screwm_review_camera_origin_z = screwm_clamp(screwm_review_camera_origin_z, 24, 340);
    }
    else if (cvar("screwm_csqc_manual_camera") > 0 && manual > 0)
    {
        screwm_review_camera_origin_x = screwm_read_float("data/camera-origin-x.txt", screwm_review_camera_origin_x);
        screwm_review_camera_origin_y = screwm_read_float("data/camera-origin-y.txt", screwm_review_camera_origin_y);
        screwm_review_camera_origin_z = screwm_read_float("data/camera-origin-z.txt", screwm_review_camera_origin_z);
        screwm_review_camera_angles_x = screwm_read_float("data/camera-pitch.txt", screwm_review_camera_angles_x);
        screwm_review_camera_angles_y = screwm_read_float("data/camera-yaw.txt", screwm_review_camera_angles_y);
        screwm_review_camera_angles_z = 0;
        fov = screwm_read_float("data/camera-fov.txt", 76);
        screwm_review_camera_fov_x = fov;
        screwm_review_camera_fov_y = fov * 0.625;
    }
    else if (cvar("screwm_csqc_review_path") > 0)
    {
        phase = time * screwm_review_camera_two_pi / screwm_review_camera_period;
        lift_phase = phase * 0.5 + 1.5708;
        screwm_review_camera_origin_x = sin(phase) * 84;
        screwm_review_camera_origin_y = -650 + cos(phase) * 20;
        screwm_review_camera_origin_z = 190 + sin(lift_phase) * 12;
        screwm_review_camera_angles = vectoangles('0 -405 176' - screwm_review_camera_origin);
        screwm_review_camera_angles_z = 0;
        screwm_review_camera_fov = '78 49 0';
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

void(vector org, float idx, vector color, float active, float presence) screwm_add_ward_light =
{
    float radius;
    float homage_boost;

    radius = 22 + screwm_energy * 18 + screwm_voice * 32 + active * 74;
    radius = radius + presence * 56;
    radius = radius + screwm_audio_rms * 12 + screwm_audio_onset * 20;
    homage_boost = screwm_homage_quake * (7 + screwm_homage_transition * 28 + screwm_homage_signature * 22);
    radius = radius + homage_boost;
    adddynamiclight(org, screwm_clamp(radius, 14, 78), color);
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

    radius = 16 + screwm_energy * 22 + signal * 92;
    radius = radius + screwm_audio_onset * 18 + screwm_homage_quake * (8 + screwm_homage_transition * 20);
    adddynamiclight(org, screwm_clamp(radius, 10, 120), color);
};

void(vector org, float idx, vector color, float signal, float fresh) screwm_add_scene_graph_light =
{
    float radius;

    radius = 14 + screwm_energy * 18 + signal * 64 + fresh * 52;
    radius = radius + screwm_audio_rms * 10 + screwm_homage_quake * (6 + screwm_homage_signature * 18);
    adddynamiclight(org, screwm_clamp(radius, 10, 104), color);
};

void(vector org, float idx, vector color, float signal) screwm_add_local_effect_light =
{
    float radius;

    radius = 12 + screwm_energy * 16 + signal * 104;
    radius = radius + screwm_reverie_temporal * 16 + screwm_reverie_material * 18;
    radius = radius + screwm_audio_onset * 20 + screwm_homage_signature * 14;
    adddynamiclight(org, screwm_clamp(radius, 8, 128), color);
};

void(vector org, float idx, vector color, float active_src, float active_dst) screwm_add_drift_light =
{
    float activity;
    float radius;
    float homage_boost;

    activity = screwm_clamp(active_src + active_dst, 0, 1);
    radius = 18 + screwm_energy * 20 + activity * 58;
    radius = radius + screwm_audio_rms * 18 + screwm_audio_onset * 34;
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

    material_field = screwm_reverie_material + screwm_audio_rms * 0.55 + screwm_homage_signature * 0.35;
    spectral_field = screwm_reverie_spectral + screwm_audio_onset * 0.40 + screwm_homage_transition * 0.30;
    temporal_field = screwm_reverie_temporal + screwm_audio_onset * 0.35;
    thermal_field = screwm_reverie_thermal + screwm_homage_quake * 0.28;

    adddynamiclight('0 -520 326', screwm_clamp(42 + material_field * 96, 24, 138), screwm_cyan);
    adddynamiclight('0 -488 252', screwm_clamp(26 + spectral_field * 76, 14, 106), screwm_green);
    adddynamiclight('-150 -490 300', screwm_clamp(22 + material_field * 64, 12, 92), screwm_amber);
    adddynamiclight('144 -488 260', screwm_clamp(22 + thermal_field * 72, 12, 104), screwm_rose);
    adddynamiclight('-96 -448 104', screwm_clamp(18 + temporal_field * 58, 10, 84), screwm_green);
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

void() screwm_add_local_effect_lights =
{
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

    pulse = 170 + screwm_energy * 80 + screwm_audio_rms * 90;
    voice_radius = 20 + screwm_voice * 90 + screwm_audio_onset * 40;

    adddynamiclight('0 -455 176', pulse + voice_radius, '1.0 0.58 0.18');
    if (cvar("screwm_review_fill_light") > 0)
        adddynamiclight('0 -332 184', 220 + screwm_energy * 80, '0.74 0.58 0.38');
    adddynamiclight('-222 -360 280', 70 + screwm_energy * 40, screwm_cyan);
    adddynamiclight('222 -360 226', 70 + screwm_voice * 80, screwm_rose);
    adddynamiclight('-222 -360 118', 58 + screwm_energy * 34, screwm_green);
    adddynamiclight('222 -360 64', 58 + screwm_voice * 70, screwm_amber);
    screwm_add_homage_lights();
    screwm_add_material_field_lights();
    screwm_add_visual_layer_lights();
    screwm_add_local_effect_lights();

    screwm_add_ward_light('-222 -360 280', 1, screwm_cyan, screwm_active_01, screwm_presence_01);
    screwm_add_ward_light('-148 -360 280', 2, screwm_rose, screwm_active_02, screwm_presence_02);
    screwm_add_ward_light('-74 -360 280', 3, screwm_green, screwm_active_03, screwm_presence_03);
    screwm_add_ward_light('0 -360 280', 4, screwm_green, screwm_active_04, screwm_presence_04);
    screwm_add_ward_light('74 -360 280', 5, screwm_green, screwm_active_05, screwm_presence_05);
    screwm_add_ward_light('148 -360 280', 6, screwm_cyan, screwm_active_06, screwm_presence_06);
    screwm_add_ward_light('222 -360 280', 7, screwm_amber, screwm_active_07, screwm_presence_07);

    screwm_add_ward_light('-222 -360 226', 8, screwm_green, screwm_active_08, screwm_presence_08);
    screwm_add_ward_light('-148 -360 226', 9, screwm_amber, screwm_active_09, screwm_presence_09);
    screwm_add_ward_light('-74 -360 226', 10, screwm_green, screwm_active_10, screwm_presence_10);
    screwm_add_ward_light('0 -360 226', 11, screwm_cyan, screwm_active_11, screwm_presence_11);
    screwm_add_ward_light('74 -360 226', 12, screwm_amber, screwm_active_12, screwm_presence_12);
    screwm_add_ward_light('148 -360 226', 13, screwm_amber, screwm_active_13, screwm_presence_13);
    screwm_add_ward_light('222 -360 226', 14, screwm_cyan, screwm_active_14, screwm_presence_14);

    screwm_add_ward_light('-222 -360 172', 15, screwm_amber, screwm_active_15, screwm_presence_15);
    screwm_add_ward_light('-148 -360 172', 16, screwm_green, screwm_active_16, screwm_presence_16);
    screwm_add_ward_light('-74 -360 172', 17, screwm_cyan, screwm_active_17, screwm_presence_17);
    screwm_add_ward_light('0 -360 172', 18, screwm_rose, screwm_active_18, screwm_presence_18);
    screwm_add_ward_light('74 -360 172', 19, screwm_rose, screwm_active_19, screwm_presence_19);
    screwm_add_ward_light('148 -360 172', 20, screwm_amber, screwm_active_20, screwm_presence_20);
    screwm_add_ward_light('222 -360 172', 21, screwm_amber, screwm_active_21, screwm_presence_21);

    screwm_add_ward_light('-222 -360 118', 22, screwm_amber, screwm_active_22, screwm_presence_22);
    screwm_add_ward_light('-148 -360 118', 23, screwm_cyan, screwm_active_23, screwm_presence_23);
    screwm_add_ward_light('-74 -360 118', 24, screwm_cyan, screwm_active_24, screwm_presence_24);
    screwm_add_ward_light('0 -360 118', 25, screwm_green, screwm_active_25, screwm_presence_25);
    screwm_add_ward_light('74 -360 118', 26, screwm_green, screwm_active_26, screwm_presence_26);
    screwm_add_ward_light('148 -360 118', 27, screwm_amber, screwm_active_27, screwm_presence_27);
    screwm_add_ward_light('222 -360 118', 28, screwm_amber, screwm_active_28, screwm_presence_28);

    screwm_add_ward_light('-222 -360 64', 29, screwm_rose, screwm_active_29, screwm_presence_29);
    screwm_add_ward_light('-148 -360 64', 30, screwm_cyan, screwm_active_30, screwm_presence_30);
    screwm_add_ward_light('-74 -360 64', 31, screwm_cyan, screwm_active_31, screwm_presence_31);
    screwm_add_ward_light('0 -360 64', 32, screwm_cyan, screwm_active_32, screwm_presence_32);
    screwm_add_ward_light('74 -360 64', 33, screwm_cyan, screwm_active_33, screwm_presence_33);
    screwm_add_ward_light('148 -360 64', 34, screwm_green, screwm_active_34, screwm_presence_34);
    screwm_add_ward_light('222 -360 64', 35, screwm_rose, screwm_active_35, screwm_presence_35);
    screwm_add_ward_light('0 -360 28', 36, screwm_green, screwm_active_36, screwm_presence_36);

    screwm_add_drift_light('-185 -378 253', 1, screwm_cyan, screwm_active_01, screwm_active_09);
    screwm_add_drift_light('-111 -378 253', 2, screwm_amber, screwm_active_02, screwm_active_10);
    screwm_add_drift_light('-37 -378 253', 3, screwm_rose, screwm_active_03, screwm_active_11);
    screwm_add_drift_light('37 -378 253', 4, screwm_green, screwm_active_04, screwm_active_12);
    screwm_add_drift_light('111 -378 253', 5, screwm_cyan, screwm_active_05, screwm_active_13);
    screwm_add_drift_light('185 -378 253', 6, screwm_amber, screwm_active_06, screwm_active_14);
    screwm_add_drift_light('0 -378 226', 7, screwm_amber, screwm_active_07, screwm_active_15);
    screwm_add_drift_light('-185 -378 199', 8, screwm_green, screwm_active_08, screwm_active_16);
    screwm_add_drift_light('-185 -378 145', 9, screwm_green, screwm_active_15, screwm_active_23);
    screwm_add_drift_light('-111 -378 145', 10, screwm_cyan, screwm_active_16, screwm_active_24);
    screwm_add_drift_light('-37 -378 145', 11, screwm_cyan, screwm_active_17, screwm_active_25);
    screwm_add_drift_light('37 -378 145', 12, screwm_rose, screwm_active_18, screwm_active_26);
    screwm_add_drift_light('111 -378 145', 13, screwm_rose, screwm_active_19, screwm_active_27);
    screwm_add_drift_light('185 -378 145', 14, screwm_amber, screwm_active_20, screwm_active_28);
    screwm_add_drift_light('222 -378 145', 15, screwm_amber, screwm_active_21, screwm_active_28);
    screwm_add_drift_light('-185 -378 91', 16, screwm_amber, screwm_active_22, screwm_active_30);
    screwm_add_drift_light('-74 -378 91', 17, screwm_cyan, screwm_active_24, screwm_active_31);
    screwm_add_drift_light('148 -378 91', 18, screwm_amber, screwm_active_27, screwm_active_34);
    screwm_add_drift_light('0 -378 226', 19, screwm_cyan, screwm_active_04, screwm_active_18);
    screwm_add_drift_light('0 -378 118', 20, screwm_green, screwm_active_18, screwm_active_32);
    screwm_add_drift_light('0 -378 64', 21, screwm_rose, screwm_active_29, screwm_active_35);
    screwm_add_drift_light('-37 -378 64', 22, screwm_cyan, screwm_active_30, screwm_active_33);
    screwm_add_drift_light('37 -378 64', 23, screwm_cyan, screwm_active_31, screwm_active_34);
    screwm_add_drift_light('37 -378 46', 24, screwm_cyan, screwm_active_33, screwm_active_36);
    screwm_add_drift_light('74 -378 46', 25, screwm_green, screwm_active_34, screwm_active_36);
    screwm_add_drift_light('0 -378 73', 26, screwm_rose, screwm_active_25, screwm_active_36);
    screwm_add_drift_light('0 -378 46', 27, screwm_cyan, screwm_active_32, screwm_active_36);

    screwm_add_source_light('-312 -88 286', 1, screwm_amber, screwm_source_priority_01, screwm_source_fresh_01);
    screwm_add_source_light('-312 -88 174', 2, screwm_green, screwm_source_priority_02, screwm_source_fresh_02);
    screwm_add_source_light('-312 -88 62', 3, screwm_rose, screwm_source_priority_03, screwm_source_fresh_03);
    screwm_add_source_light('312 -88 286', 4, screwm_cyan, screwm_source_priority_04, screwm_source_fresh_04);
    screwm_add_source_light('312 -88 174', 5, screwm_green, screwm_source_priority_05, screwm_source_fresh_05);
    screwm_add_source_light('312 -88 62', 6, screwm_green, screwm_source_priority_06, screwm_source_fresh_06);

    screwm_add_aoa_pane_light('-4 -497 284', 1, screwm_cyan, screwm_aoa_pane_01);
    screwm_add_aoa_pane_light('-72 -497 238', 2, screwm_green, screwm_aoa_pane_02);
    screwm_add_aoa_pane_light('72 -497 238', 3, screwm_amber, screwm_aoa_pane_03);
    screwm_add_aoa_pane_light('-118 -497 170', 4, screwm_rose, screwm_aoa_pane_04);
    screwm_add_aoa_pane_light('118 -497 170', 5, screwm_cyan, screwm_aoa_pane_05);
    screwm_add_aoa_pane_light('-76 -497 102', 6, screwm_green, screwm_aoa_pane_06);
    screwm_add_aoa_pane_light('76 -497 102', 7, screwm_amber, screwm_aoa_pane_07);
    screwm_add_aoa_pane_light('-176 -497 216', 8, screwm_rose, screwm_aoa_pane_08);
    screwm_add_aoa_pane_light('176 -497 216', 9, screwm_cyan, screwm_aoa_pane_09);
    screwm_add_aoa_pane_light('0 -497 64', 10, screwm_green, screwm_aoa_pane_10);

    screwm_add_scene_graph_light('-300 -460 276', 1, screwm_amber, screwm_source_priority_01, screwm_source_fresh_01);
    screwm_add_scene_graph_light('-300 -450 190', 2, screwm_green, screwm_source_priority_02, screwm_source_fresh_02);
    screwm_add_scene_graph_light('-300 -440 104', 3, screwm_rose, screwm_source_priority_03, screwm_source_fresh_03);
    screwm_add_scene_graph_light('-178 -454 328', 4, screwm_cyan, screwm_source_priority_04, screwm_source_fresh_04);
    screwm_add_scene_graph_light('-94 -460 346', 5, screwm_green, screwm_source_priority_05, screwm_source_fresh_05);
    screwm_add_scene_graph_light('-10 -454 328', 6, screwm_cyan, screwm_source_priority_06, screwm_source_fresh_06);
    screwm_add_scene_graph_light('74 -446 308', 7, screwm_green, screwm_active_36, screwm_source_fresh_06);
    screwm_add_scene_graph_light('288 -456 260', 8, screwm_amber, screwm_active_23, screwm_active_23);
    screwm_add_scene_graph_light('292 -446 182', 9, screwm_cyan, screwm_active_24, screwm_active_24);
    screwm_add_scene_graph_light('284 -436 104', 10, screwm_amber, screwm_active_30, screwm_active_30);
    screwm_add_scene_graph_light('176 -420 36', 11, screwm_green, screwm_active_26, screwm_active_26);
    screwm_add_scene_graph_light('96 -416 12', 12, screwm_amber, screwm_active_10, screwm_active_10);
    screwm_add_scene_graph_light('-114 -386 14', 13, screwm_cyan, screwm_active_14, screwm_active_14);
    screwm_add_scene_graph_light('-186 -380 38', 14, screwm_rose, screwm_active_35, screwm_active_35);
};

void(float apilevel, string enginename, float engineversion) CSQC_Init =
{
    screwm_energy = 0.5;
    screwm_voice = 0;
    screwm_mode = "rnd";
    screwm_next_poll = 0;
    screwm_review_camera_origin = '0 -650 190';
    screwm_review_camera_angles = vectoangles('0 -405 176' - screwm_review_camera_origin);
    screwm_review_camera_angles_z = 0;
    screwm_review_camera_fov = '78 49 0';
    screwm_review_camera_period = 110.0;
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
