// Screwm CSQC - in-engine ward identity, drift links, and pulse lighting.

float screwm_width;
float screwm_height;
float screwm_next_poll;
float screwm_energy;
float screwm_voice;
float screwm_audio_rms;
float screwm_audio_onset;
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

vector screwm_cyan = '0.45 0.95 0.88';
vector screwm_amber = '1.00 0.62 0.23';
vector screwm_rose = '1.00 0.35 0.55';
vector screwm_green = '0.55 0.85 0.42';
vector screwm_dim = '0.10 0.13 0.14';

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

float(string path) screwm_read_norm =
{
    string line;

    line = screwm_read_line(path, "0");
    return screwm_clamp(stof(line), 0, 1);
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

void(vector org, float idx, vector color, float active) screwm_add_ward_light =
{
    float radius;

    radius = 22 + screwm_energy * 18 + screwm_voice * 32 + active * 74;
    radius = radius + screwm_audio_rms * 12 + screwm_audio_onset * 20;
    radius = radius + 4 * sin(time * 1.15 + idx * 0.47);
    if (active > 0)
        radius = radius + 10 * sin(time * 3.4 + idx * 0.29);
    adddynamiclight(org, screwm_clamp(radius, 14, 78), color);
};

void(vector org, float idx, vector color, float priority, float fresh) screwm_add_source_light =
{
    float radius;

    radius = 16 + priority * 36 + fresh * 84;
    radius = radius + screwm_audio_rms * 8 + screwm_audio_onset * 14;
    radius = radius + 5 * sin(time * (0.9 + fresh * 1.2) + idx * 0.61);
    adddynamiclight(org, screwm_clamp(radius, 12, 118), color);
};

void(vector org, float idx, vector color, float active_src, float active_dst) screwm_add_drift_light =
{
    float activity;
    float radius;

    activity = screwm_clamp(active_src + active_dst, 0, 1);
    radius = 18 + screwm_energy * 20 + activity * 58;
    radius = radius + screwm_audio_rms * 18 + screwm_audio_onset * 34;
    radius = radius + 6 * sin(time * (1.0 + activity * 1.8) + idx * 0.37);
    adddynamiclight(org, screwm_clamp(radius, 12, 94), color);
};

void() screwm_draw_ward_links =
{
    vector c01;
    vector c02;
    vector c03;
    vector c04;
    vector c05;

    c01 = '0 62 280';
    c02 = '0 26 226';
    c03 = '0 -10 172';
    c04 = '0 -46 118';
    c05 = '0 -82 64';

    screwm_draw_link('-222 62 280', '-148 26 226', 0.0, screwm_cyan);
    screwm_draw_link('-148 62 280', '-74 26 226', 0.6, screwm_amber);
    screwm_draw_link('-74 62 280', c02, 1.2, screwm_rose);
    screwm_draw_link(c01, '74 26 226', 1.8, screwm_green);
    screwm_draw_link('74 62 280', '148 26 226', 2.4, screwm_cyan);
    screwm_draw_link('148 62 280', '222 26 226', 3.0, screwm_amber);

    screwm_draw_link('-222 -10 172', '-148 -46 118', 3.6, screwm_green);
    screwm_draw_link('-74 -10 172', c04, 4.2, screwm_cyan);
    screwm_draw_link(c03, '74 -46 118', 4.8, screwm_rose);
    screwm_draw_link('148 -10 172', '222 -46 118', 5.4, screwm_amber);

    screwm_draw_link(c01, c03, 6.0, screwm_cyan);
    screwm_draw_link(c03, c05, 6.6, screwm_green);
    screwm_draw_link('-222 -82 64', '222 -82 64', 7.2, screwm_rose);
    screwm_draw_link('0 -46 118', '0 -118 28', 7.8, screwm_rose);
    screwm_draw_link('0 -82 64', '0 -118 28', 8.4, screwm_cyan);
};

void() screwm_draw_wards =
{
    screwm_draw_ward_links();

    screwm_draw_ward_label('-222 62 280', "01", "TOKEN", 1, screwm_cyan);
    screwm_draw_ward_label('-148 62 280', "02", "ALBUM", 2, screwm_rose);
    screwm_draw_ward_label('-74 62 280', "03", "STREAM", 3, screwm_green);
    screwm_draw_ward_label('0 62 280', "04", "SIERP", 4, screwm_green);
    screwm_draw_ward_label('74 62 280', "05", "REVERIE", 5, screwm_green);
    screwm_draw_ward_label('148 62 280', "06", "ACT", 6, screwm_cyan);
    screwm_draw_ward_label('222 62 280', "07", "STANCE", 7, screwm_amber);

    screwm_draw_ward_label('-222 26 226', "08", "GEM", 8, screwm_green);
    screwm_draw_ward_label('-148 26 226', "09", "GROUND", 9, screwm_amber);
    screwm_draw_ward_label('-74 26 226', "10", "IMPINGE", 10, screwm_green);
    screwm_draw_ward_label('0 26 226', "11", "RECRUIT", 11, screwm_cyan);
    screwm_draw_ward_label('74 26 226', "12", "THINK", 12, screwm_amber);
    screwm_draw_ward_label('148 26 226', "13", "PRESS", 13, screwm_amber);
    screwm_draw_ward_label('222 26 226', "14", "VARIETY", 14, screwm_cyan);

    screwm_draw_ward_label('-222 -10 172', "15", "HERE", 15, screwm_amber);
    screwm_draw_ward_label('-148 -10 172', "16", "DURF", 16, screwm_green);
    screwm_draw_ward_label('-74 -10 172', "17", "CODE", 17, screwm_cyan);
    screwm_draw_ward_label('0 -10 172', "18", "M8", 18, screwm_rose);
    screwm_draw_ward_label('74 -10 172', "19", "DECK", 19, screwm_rose);
    screwm_draw_ward_label('148 -10 172', "20", "EGRESS", 20, screwm_amber);
    screwm_draw_ward_label('222 -10 172', "21", "BANNER", 21, screwm_amber);

    screwm_draw_ward_label('-222 -46 118', "22", "PRECED", 22, screwm_amber);
    screwm_draw_ward_label('-148 -46 118', "23", "HISTORY", 23, screwm_cyan);
    screwm_draw_ward_label('-74 -46 118', "24", "INSTR", 24, screwm_cyan);
    screwm_draw_ward_label('0 -46 118', "25", "CBIP", 25, screwm_green);
    screwm_draw_ward_label('74 -46 118', "26", "CHAT", 26, screwm_green);
    screwm_draw_ward_label('148 -46 118', "27", "CHRON", 27, screwm_amber);
    screwm_draw_ward_label('222 -46 118', "28", "STATE", 28, screwm_amber);

    screwm_draw_ward_label('-222 -82 64', "29", "POLYEND", 29, screwm_rose);
    screwm_draw_ward_label('-148 -82 64', "30", "QUERY", 30, screwm_cyan);
    screwm_draw_ward_label('-74 -82 64', "31", "POSTER", 31, screwm_cyan);
    screwm_draw_ward_label('0 -82 64', "32", "TUFTE", 32, screwm_cyan);
    screwm_draw_ward_label('74 -82 64', "33", "ASCII", 33, screwm_cyan);
    screwm_draw_ward_label('148 -82 64', "34", "SEGMENT", 34, screwm_green);
    screwm_draw_ward_label('222 -82 64', "35", "SCOPE", 35, screwm_rose);
    screwm_draw_ward_label('0 -118 28', "36", "IRDUAL", 36, screwm_green);

    screwm_draw_ward_detail('-222 62 280', screwm_w01, 1, screwm_cyan);
    screwm_draw_ward_detail('-148 62 280', screwm_w02, 2, screwm_rose);
    screwm_draw_ward_detail('-74 62 280', screwm_w03, 3, screwm_green);
    screwm_draw_ward_detail('0 62 280', screwm_w04, 4, screwm_green);
    screwm_draw_ward_detail('74 62 280', screwm_w05, 5, screwm_green);
    screwm_draw_ward_detail('148 62 280', screwm_w06, 6, screwm_cyan);
    screwm_draw_ward_detail('222 62 280', screwm_w07, 7, screwm_amber);
    screwm_draw_ward_detail('-222 26 226', screwm_w08, 8, screwm_green);
    screwm_draw_ward_detail('-148 26 226', screwm_w09, 9, screwm_amber);
    screwm_draw_ward_detail('-74 26 226', screwm_w10, 10, screwm_green);
    screwm_draw_ward_detail('0 26 226', screwm_w11, 11, screwm_cyan);
    screwm_draw_ward_detail('74 26 226', screwm_w12, 12, screwm_amber);
    screwm_draw_ward_detail('148 26 226', screwm_w13, 13, screwm_amber);
    screwm_draw_ward_detail('222 26 226', screwm_w14, 14, screwm_cyan);
    screwm_draw_ward_detail('-222 -10 172', screwm_w15, 15, screwm_amber);
    screwm_draw_ward_detail('-148 -10 172', screwm_w16, 16, screwm_green);
    screwm_draw_ward_detail('-74 -10 172', screwm_w17, 17, screwm_cyan);
    screwm_draw_ward_detail('0 -10 172', screwm_w18, 18, screwm_rose);
    screwm_draw_ward_detail('74 -10 172', screwm_w19, 19, screwm_rose);
    screwm_draw_ward_detail('148 -10 172', screwm_w20, 20, screwm_amber);
    screwm_draw_ward_detail('222 -10 172', screwm_w21, 21, screwm_amber);
    screwm_draw_ward_detail('-222 -46 118', screwm_w22, 22, screwm_amber);
    screwm_draw_ward_detail('-148 -46 118', screwm_w23, 23, screwm_cyan);
    screwm_draw_ward_detail('-74 -46 118', screwm_w24, 24, screwm_cyan);
    screwm_draw_ward_detail('0 -46 118', screwm_w25, 25, screwm_green);
    screwm_draw_ward_detail('74 -46 118', screwm_w26, 26, screwm_green);
    screwm_draw_ward_detail('148 -46 118', screwm_w27, 27, screwm_amber);
    screwm_draw_ward_detail('222 -46 118', screwm_w28, 28, screwm_amber);
    screwm_draw_ward_detail('-222 -82 64', screwm_w29, 29, screwm_rose);
    screwm_draw_ward_detail('-148 -82 64', screwm_w30, 30, screwm_cyan);
    screwm_draw_ward_detail('-74 -82 64', screwm_w31, 31, screwm_cyan);
    screwm_draw_ward_detail('0 -82 64', screwm_w32, 32, screwm_cyan);
    screwm_draw_ward_detail('74 -82 64', screwm_w33, 33, screwm_cyan);
    screwm_draw_ward_detail('148 -82 64', screwm_w34, 34, screwm_green);
    screwm_draw_ward_detail('222 -82 64', screwm_w35, 35, screwm_rose);
    screwm_draw_ward_detail('0 -118 28', screwm_w36, 36, screwm_green);
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
    pulse = pulse + 18 * sin(time * (1.1 + screwm_audio_onset * 1.8));
    voice_radius = 20 + screwm_voice * 90 + screwm_audio_onset * 40;

    adddynamiclight('0 40 176', pulse + voice_radius, '1.0 0.58 0.18');
    adddynamiclight('-222 62 280', 70 + screwm_energy * 40, screwm_cyan);
    adddynamiclight('222 26 226', 70 + screwm_voice * 80, screwm_rose);
    adddynamiclight('-222 -46 118', 58 + screwm_energy * 34, screwm_green);
    adddynamiclight('222 -82 64', 58 + screwm_voice * 70, screwm_amber);

    screwm_add_ward_light('-222 62 280', 1, screwm_cyan, screwm_active_01);
    screwm_add_ward_light('-148 62 280', 2, screwm_rose, screwm_active_02);
    screwm_add_ward_light('-74 62 280', 3, screwm_green, screwm_active_03);
    screwm_add_ward_light('0 62 280', 4, screwm_green, screwm_active_04);
    screwm_add_ward_light('74 62 280', 5, screwm_green, screwm_active_05);
    screwm_add_ward_light('148 62 280', 6, screwm_cyan, screwm_active_06);
    screwm_add_ward_light('222 62 280', 7, screwm_amber, screwm_active_07);

    screwm_add_ward_light('-222 26 226', 8, screwm_green, screwm_active_08);
    screwm_add_ward_light('-148 26 226', 9, screwm_amber, screwm_active_09);
    screwm_add_ward_light('-74 26 226', 10, screwm_green, screwm_active_10);
    screwm_add_ward_light('0 26 226', 11, screwm_cyan, screwm_active_11);
    screwm_add_ward_light('74 26 226', 12, screwm_amber, screwm_active_12);
    screwm_add_ward_light('148 26 226', 13, screwm_amber, screwm_active_13);
    screwm_add_ward_light('222 26 226', 14, screwm_cyan, screwm_active_14);

    screwm_add_ward_light('-222 -10 172', 15, screwm_amber, screwm_active_15);
    screwm_add_ward_light('-148 -10 172', 16, screwm_green, screwm_active_16);
    screwm_add_ward_light('-74 -10 172', 17, screwm_cyan, screwm_active_17);
    screwm_add_ward_light('0 -10 172', 18, screwm_rose, screwm_active_18);
    screwm_add_ward_light('74 -10 172', 19, screwm_rose, screwm_active_19);
    screwm_add_ward_light('148 -10 172', 20, screwm_amber, screwm_active_20);
    screwm_add_ward_light('222 -10 172', 21, screwm_amber, screwm_active_21);

    screwm_add_ward_light('-222 -46 118', 22, screwm_amber, screwm_active_22);
    screwm_add_ward_light('-148 -46 118', 23, screwm_cyan, screwm_active_23);
    screwm_add_ward_light('-74 -46 118', 24, screwm_cyan, screwm_active_24);
    screwm_add_ward_light('0 -46 118', 25, screwm_green, screwm_active_25);
    screwm_add_ward_light('74 -46 118', 26, screwm_green, screwm_active_26);
    screwm_add_ward_light('148 -46 118', 27, screwm_amber, screwm_active_27);
    screwm_add_ward_light('222 -46 118', 28, screwm_amber, screwm_active_28);

    screwm_add_ward_light('-222 -82 64', 29, screwm_rose, screwm_active_29);
    screwm_add_ward_light('-148 -82 64', 30, screwm_cyan, screwm_active_30);
    screwm_add_ward_light('-74 -82 64', 31, screwm_cyan, screwm_active_31);
    screwm_add_ward_light('0 -82 64', 32, screwm_cyan, screwm_active_32);
    screwm_add_ward_light('74 -82 64', 33, screwm_cyan, screwm_active_33);
    screwm_add_ward_light('148 -82 64', 34, screwm_green, screwm_active_34);
    screwm_add_ward_light('222 -82 64', 35, screwm_rose, screwm_active_35);
    screwm_add_ward_light('0 -118 28', 36, screwm_green, screwm_active_36);

    screwm_add_drift_light('-185 34 253', 1, screwm_cyan, screwm_active_01, screwm_active_09);
    screwm_add_drift_light('-111 34 253', 2, screwm_amber, screwm_active_02, screwm_active_10);
    screwm_add_drift_light('-37 34 253', 3, screwm_rose, screwm_active_03, screwm_active_11);
    screwm_add_drift_light('37 34 253', 4, screwm_green, screwm_active_04, screwm_active_12);
    screwm_add_drift_light('111 34 253', 5, screwm_cyan, screwm_active_05, screwm_active_13);
    screwm_add_drift_light('185 34 253', 6, screwm_amber, screwm_active_06, screwm_active_14);
    screwm_add_drift_light('0 16 226', 7, screwm_amber, screwm_active_07, screwm_active_15);
    screwm_add_drift_light('-185 -2 199', 8, screwm_green, screwm_active_08, screwm_active_16);
    screwm_add_drift_light('-185 -38 145', 9, screwm_green, screwm_active_15, screwm_active_23);
    screwm_add_drift_light('-111 -38 145', 10, screwm_cyan, screwm_active_16, screwm_active_24);
    screwm_add_drift_light('-37 -38 145', 11, screwm_cyan, screwm_active_17, screwm_active_25);
    screwm_add_drift_light('37 -38 145', 12, screwm_rose, screwm_active_18, screwm_active_26);
    screwm_add_drift_light('111 -38 145', 13, screwm_rose, screwm_active_19, screwm_active_27);
    screwm_add_drift_light('185 -38 145', 14, screwm_amber, screwm_active_20, screwm_active_28);
    screwm_add_drift_light('222 -38 145', 15, screwm_amber, screwm_active_21, screwm_active_28);
    screwm_add_drift_light('-185 -74 91', 16, screwm_amber, screwm_active_22, screwm_active_30);
    screwm_add_drift_light('-74 -74 91', 17, screwm_cyan, screwm_active_24, screwm_active_31);
    screwm_add_drift_light('148 -74 91', 18, screwm_amber, screwm_active_27, screwm_active_34);
    screwm_add_drift_light('0 16 226', 19, screwm_cyan, screwm_active_04, screwm_active_18);
    screwm_add_drift_light('0 -56 118', 20, screwm_green, screwm_active_18, screwm_active_32);
    screwm_add_drift_light('0 -92 64', 21, screwm_rose, screwm_active_29, screwm_active_35);
    screwm_add_drift_light('-37 -92 64', 22, screwm_cyan, screwm_active_30, screwm_active_33);
    screwm_add_drift_light('37 -92 64', 23, screwm_cyan, screwm_active_31, screwm_active_34);
    screwm_add_drift_light('37 -110 46', 24, screwm_cyan, screwm_active_33, screwm_active_36);
    screwm_add_drift_light('74 -110 46', 25, screwm_green, screwm_active_34, screwm_active_36);
    screwm_add_drift_light('0 -92 73', 26, screwm_rose, screwm_active_25, screwm_active_36);
    screwm_add_drift_light('0 -110 46', 27, screwm_cyan, screwm_active_32, screwm_active_36);

    screwm_add_source_light('-244 112 286', 1, screwm_amber, screwm_source_priority_01, screwm_source_fresh_01);
    screwm_add_source_light('-244 112 174', 2, screwm_green, screwm_source_priority_02, screwm_source_fresh_02);
    screwm_add_source_light('-244 112 62', 3, screwm_rose, screwm_source_priority_03, screwm_source_fresh_03);
    screwm_add_source_light('244 112 286', 4, screwm_cyan, screwm_source_priority_04, screwm_source_fresh_04);
    screwm_add_source_light('244 112 174', 5, screwm_green, screwm_source_priority_05, screwm_source_fresh_05);
    screwm_add_source_light('244 112 62', 6, screwm_green, screwm_source_priority_06, screwm_source_fresh_06);
};

void(float apilevel, string enginename, float engineversion) CSQC_Init =
{
    screwm_energy = 0.5;
    screwm_voice = 0;
    screwm_mode = "rnd";
    screwm_next_poll = 0;
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
