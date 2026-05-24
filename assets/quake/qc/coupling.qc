// Screwm QuakeC — live cognitive coupling
// Reads /dev/shm state files to drive tower behavior

float coupling_next_poll;
float coupling_poll_interval;
float coupling_energy;
float coupling_voice_active;
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
    coupling_next_poll = time + 0.5;
    coupling_current_mode = "rnd";
    coupling_mode_check_next = time + 5.0;
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

void() coupling_apply_stimmung =
{
    // AoA rotation speed: faster with voice activity
    if (aoa_entity)
    {
        float base_rot = 3.0;
        float voice_boost = coupling_voice_active * 8.0;
        aoa_entity.screwm_spin_y = base_rot + voice_boost + coupling_energy * 4.0;
    }

    // Fog density: denser at low energy (contemplative), clearer at high
    float fog_density = 0.03 - coupling_energy * 0.02;
    localcmd(strcat(strcat("fog ", ftos(fog_density)), " 0.08 0.06 0.10\n"));

    // Post-processing modulation from cognitive state. These are spatial
    // scroom fields, not fourth-wall camera filters.
    // UserVec1: x=atmo_darken, y=prismatic_fog, z=world_warmth, w=dust
    float vig = 0.4 + (1.0 - coupling_energy) * 0.25;
    float ca = 0.4 + coupling_voice_active * 0.6;
    float temp_val = 0.10 + coupling_energy * 0.08;
    float grain_val = 0.02 + (1.0 - coupling_energy) * 0.02;
    string uservec1_cmd;
    uservec1_cmd = strcat("r_glsl_postprocess_uservec1 \"", ftos(vig));
    uservec1_cmd = strcat(uservec1_cmd, " ");
    uservec1_cmd = strcat(uservec1_cmd, ftos(ca));
    uservec1_cmd = strcat(uservec1_cmd, " ");
    uservec1_cmd = strcat(uservec1_cmd, ftos(temp_val));
    uservec1_cmd = strcat(uservec1_cmd, " ");
    uservec1_cmd = strcat(uservec1_cmd, ftos(grain_val));
    uservec1_cmd = strcat(uservec1_cmd, "\"\n");
    localcmd(uservec1_cmd);

    // UserVec2: x=mortar_lines, y=edge_glow, z=posterize, w=unused
    float edge = 0.15 + coupling_energy * 0.25;
    string uservec2_cmd;
    uservec2_cmd = strcat("r_glsl_postprocess_uservec2 \"0.06 ", ftos(edge));
    uservec2_cmd = strcat(uservec2_cmd, " 0 0\"\n");
    localcmd(uservec2_cmd);

    // UserVec3: x=spatial_warp, y=signal_noise, z=halftone, w=threshold.
    // Keep warp/halftone/threshold disabled in the review baseline; let the
    // live state breathe through subtle signal noise instead.
    float noise_val = 0.004 + (1.0 - coupling_energy) * 0.006 + coupling_voice_active * 0.004;
    string uservec3_cmd;
    uservec3_cmd = strcat("r_glsl_postprocess_uservec3 \"0 ", ftos(noise_val));
    uservec3_cmd = strcat(uservec3_cmd, " 0 0\"\n");
    localcmd(uservec3_cmd);
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
    coupling_apply_stimmung();
    coupling_check_working_mode();
};
