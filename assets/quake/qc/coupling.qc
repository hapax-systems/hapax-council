// Screwm QuakeC — live cognitive coupling
// Reads /dev/shm state files to drive tower behavior

float coupling_next_poll;
float coupling_poll_interval;
float coupling_energy;
float coupling_voice_active;

void() coupling_init =
{
    coupling_poll_interval = 1.0;
    coupling_energy = 0.5;
    coupling_voice_active = 0;
    coupling_next_poll = time + 0.5;
};

void() coupling_read_stimmung =
{
    float fh = fopen("/dev/shm/hapax-compositor/stimmung-energy.txt", FILE_READ);
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
    float fh = fopen("/dev/shm/hapax-compositor/voice-active.txt", FILE_READ);
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
    // Camera period: 120s at high energy, 150s at low energy
    CAMERA_PERIOD = 120 + (1.0 - coupling_energy) * 30.0;

    // AoA rotation speed: faster with voice activity
    if (aoa_entity)
    {
        float base_rot = 15.0;
        float voice_boost = coupling_voice_active * 30.0;
        aoa_entity.avelocity_y = base_rot + voice_boost + coupling_energy * 10.0;
    }

    // Fog density: denser at low energy (contemplative), clearer at high
    float fog_density = 0.03 - coupling_energy * 0.02;
    localcmd(strcat("fog ", ftos(fog_density), " 0.08 0.06 0.10\n"));
};

void() coupling_tick =
{
    if (time < coupling_next_poll)
        return;

    coupling_next_poll = time + coupling_poll_interval;
    coupling_read_stimmung();
    coupling_read_voice();
    coupling_apply_stimmung();
};
