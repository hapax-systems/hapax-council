// Screwm CSQC - in-engine ward identity, drift links, and pulse lighting.

float screwm_width;
float screwm_height;
float screwm_next_poll;
float screwm_energy;
float screwm_voice;
string screwm_mode;
string screwm_w01;
string screwm_w02;
string screwm_w07;
string screwm_w09;
string screwm_w12;
string screwm_w13;
string screwm_w21;
string screwm_w28;
string screwm_w34;

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

    screwm_w01 = screwm_read_line("data/ward-01.txt", "");
    screwm_w02 = screwm_read_line("data/ward-02.txt", "");
    screwm_w07 = screwm_read_line("data/ward-07.txt", "");
    screwm_w09 = screwm_read_line("data/ward-09.txt", "");
    screwm_w12 = screwm_read_line("data/ward-12.txt", "");
    screwm_w13 = screwm_read_line("data/ward-13.txt", "");
    screwm_w21 = screwm_read_line("data/ward-21.txt", "");
    screwm_w28 = screwm_read_line("data/ward-28.txt", "");
    screwm_w34 = screwm_read_line("data/ward-34.txt", "");
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
};

void() screwm_draw_wards =
{
    screwm_draw_ward_links();

    screwm_draw_ward_label('-222 62 280', "01", "TOKEN", 1, screwm_cyan);
    screwm_draw_ward_label('-148 62 280', "02", "ALBUM", 2, screwm_amber);
    screwm_draw_ward_label('-74 62 280', "03", "STREAM", 3, screwm_cyan);
    screwm_draw_ward_label('0 62 280', "04", "SIERP", 4, screwm_rose);
    screwm_draw_ward_label('74 62 280', "05", "REVERIE", 5, screwm_green);
    screwm_draw_ward_label('148 62 280', "06", "ACT", 6, screwm_cyan);
    screwm_draw_ward_label('222 62 280', "07", "STANCE", 7, screwm_amber);

    screwm_draw_ward_label('-222 26 226', "08", "GEM", 8, screwm_green);
    screwm_draw_ward_label('-148 26 226', "09", "GROUND", 9, screwm_cyan);
    screwm_draw_ward_label('-74 26 226', "10", "IMPINGE", 10, screwm_rose);
    screwm_draw_ward_label('0 26 226', "11", "RECRUIT", 11, screwm_amber);
    screwm_draw_ward_label('74 26 226', "12", "THINK", 12, screwm_cyan);
    screwm_draw_ward_label('148 26 226', "13", "PRESS", 13, screwm_green);
    screwm_draw_ward_label('222 26 226', "14", "VARIETY", 14, screwm_rose);

    screwm_draw_ward_label('-222 -10 172', "15", "HERE", 15, screwm_cyan);
    screwm_draw_ward_label('-148 -10 172', "16", "DURF", 16, screwm_amber);
    screwm_draw_ward_label('-74 -10 172', "17", "CODE", 17, screwm_green);
    screwm_draw_ward_label('0 -10 172', "18", "M8", 18, screwm_cyan);
    screwm_draw_ward_label('74 -10 172', "19", "DECK", 19, screwm_rose);
    screwm_draw_ward_label('148 -10 172', "20", "EGRESS", 20, screwm_amber);
    screwm_draw_ward_label('222 -10 172', "21", "BANNER", 21, screwm_cyan);

    screwm_draw_ward_label('-222 -46 118', "22", "PRECED", 22, screwm_green);
    screwm_draw_ward_label('-148 -46 118', "23", "HISTORY", 23, screwm_cyan);
    screwm_draw_ward_label('-74 -46 118', "24", "INSTR", 24, screwm_amber);
    screwm_draw_ward_label('0 -46 118', "25", "CBIP", 25, screwm_rose);
    screwm_draw_ward_label('74 -46 118', "26", "CHAT", 26, screwm_cyan);
    screwm_draw_ward_label('148 -46 118', "27", "CHRON", 27, screwm_green);
    screwm_draw_ward_label('222 -46 118', "28", "STATE", 28, screwm_amber);

    screwm_draw_ward_label('-222 -82 64', "29", "POLYEND", 29, screwm_cyan);
    screwm_draw_ward_label('-148 -82 64', "30", "QUERY", 30, screwm_rose);
    screwm_draw_ward_label('-74 -82 64', "31", "POSTER", 31, screwm_green);
    screwm_draw_ward_label('0 -82 64', "32", "TUFTE", 32, screwm_cyan);
    screwm_draw_ward_label('74 -82 64', "33", "ASCII", 33, screwm_amber);
    screwm_draw_ward_label('148 -82 64', "34", "SEGMENT", 34, screwm_rose);
    screwm_draw_ward_label('222 -82 64', "35", "SCOPE", 35, screwm_green);

    screwm_draw_ward_detail('-222 62 280', screwm_w01, 1, screwm_cyan);
    screwm_draw_ward_detail('-148 62 280', screwm_w02, 2, screwm_amber);
    screwm_draw_ward_detail('222 62 280', screwm_w07, 7, screwm_amber);
    screwm_draw_ward_detail('-148 26 226', screwm_w09, 9, screwm_cyan);
    screwm_draw_ward_detail('74 26 226', screwm_w12, 12, screwm_cyan);
    screwm_draw_ward_detail('148 26 226', screwm_w13, 13, screwm_green);
    screwm_draw_ward_detail('222 -10 172', screwm_w21, 21, screwm_cyan);
    screwm_draw_ward_detail('222 -46 118', screwm_w28, 28, screwm_amber);
    screwm_draw_ward_detail('148 -82 64', screwm_w34, 34, screwm_rose);
};

void() screwm_draw_header =
{
    string mode_line;
    string energy_line;
    float alpha;

    alpha = 0.44 + screwm_energy * 0.18;
    mode_line = strcat("SCREWM FIELD / DARKPLACES SUBSTRATE / ", screwm_mode);
    energy_line = strcat("WARD ANCHORS 35 / DRIFT ", ftos(screwm_energy));

    drawfill('18 18 0', '420 34 0', '0.02 0.03 0.03', 0.22, DRAWFLAG_NORMAL);
    drawstring('26 24 0', mode_line, '7 7 0', screwm_cyan, alpha, DRAWFLAG_ADDITIVE);
    drawstring('26 38 0', energy_line, '5 5 0', screwm_amber, alpha * 0.80, DRAWFLAG_ADDITIVE);
};

void() screwm_add_dynamic_lights =
{
    float pulse;
    float voice_radius;

    pulse = 170 + screwm_energy * 80 + 18 * sin(time * 1.1);
    voice_radius = 20 + screwm_voice * 90;

    adddynamiclight('0 40 176', pulse + voice_radius, '1.0 0.58 0.18');
    adddynamiclight('-222 62 280', 70 + screwm_energy * 40, screwm_cyan);
    adddynamiclight('222 26 226', 70 + screwm_voice * 80, screwm_rose);
    adddynamiclight('-222 -46 118', 58 + screwm_energy * 34, screwm_green);
    adddynamiclight('222 -82 64', 58 + screwm_voice * 70, screwm_amber);

    adddynamiclight('-222 62 280', 44 + screwm_energy * 28, screwm_cyan);
    adddynamiclight('-148 62 280', 44 + screwm_energy * 22, screwm_amber);
    adddynamiclight('222 62 280', 42 + screwm_voice * 44, screwm_amber);
    adddynamiclight('-148 26 226', 44 + screwm_energy * 28, screwm_cyan);
    adddynamiclight('74 26 226', 42 + screwm_voice * 46, screwm_cyan);
    adddynamiclight('148 26 226', 44 + screwm_energy * 30, screwm_green);
    adddynamiclight('222 -10 172', 44 + screwm_energy * 24, screwm_cyan);
    adddynamiclight('222 -46 118', 42 + screwm_energy * 26, screwm_amber);
    adddynamiclight('148 -82 64', 42 + screwm_voice * 42, screwm_rose);
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
