// Screwm QuakeC — stable review camera with optional slow orbit

float camera_phase;

float(string path, float fallback) camera_read_norm =
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

float(string path, float fallback) camera_read_float =
{
    float fh;
    string line;

    fh = fopen(path, FILE_READ);
    if (fh < 0)
        return fallback;
    line = fgets(fh);
    fclose(fh);
    if (!line)
        return fallback;

    return stof(line);
};

vector camera_look_angles(vector pos, vector target)
{
    vector ang;
    ang = vectoangles(target - pos);
    ang_z = 0;
    return ang;
};

vector camera_orbit_position(float phase)
{
    float angle = phase * CAMERA_ORBIT_TWO_PI;
    vector pos;
    pos_x = AOA_CENTER_x + cos(angle) * CAMERA_ORBIT_RADIUS;
    pos_y = AOA_CENTER_y + sin(angle) * CAMERA_ORBIT_RADIUS;
    pos_z = CAMERA_REVIEW_POS_z;
    return pos;
};

vector() camera_file_position =
{
    vector pos;

    pos_x = camera_read_float("data/camera-origin-x.txt", CAMERA_REVIEW_POS_x);
    pos_y = camera_read_float("data/camera-origin-y.txt", CAMERA_REVIEW_POS_y);
    pos_z = camera_read_float("data/camera-origin-z.txt", CAMERA_REVIEW_POS_z);
    return pos;
};

vector() camera_file_angles =
{
    vector angles;

    angles_x = camera_read_float("data/camera-pitch.txt", 3.2);
    angles_y = camera_read_float("data/camera-yaw.txt", 90);
    angles_z = 0;
    return angles;
};

void() camera_apply_file_fov =
{
    float fov_value;

    fov_value = camera_read_float("data/camera-fov.txt", 78);
    localcmd(strcat(strcat("fov ", ftos(fov_value)), "\n"));
};

void() camera_think =
{
    vector pos;
    vector target;
    vector freecam_angles;
    float use_angles;

    target = CAMERA_REVIEW_TARGET;
    use_angles = 0;
    if (
        cvar("screwm_camera_file_control") > 0
        && camera_read_norm("data/camera-manual.txt", 0) > 0
    )
    {
        pos = camera_file_position();
        freecam_angles = camera_file_angles();
        use_angles = 1;
        camera_apply_file_fov();
        camera_phase = 0;
    }
    else if (cvar("screwm_camera_orbit") > 0)
    {
        camera_phase = camera_phase + frametime / CAMERA_ORBIT_PERIOD;
        if (camera_phase >= 1.0)
            camera_phase = camera_phase - 1.0;
        pos = camera_orbit_position(camera_phase);
    }
    else
    {
        pos = CAMERA_REVIEW_POS;
        camera_phase = 0;
    }

    setorigin(self, pos);
    if (use_angles)
        self.angles = freecam_angles;
    else
        self.angles = camera_look_angles(pos, target);
    self.nextthink = time + 0.0333;
};

void() spawn_camera =
{
    camera_entity = spawn();
    camera_entity.classname = "camera";
    camera_entity.movetype = MOVETYPE_NONE;
    camera_entity.solid = SOLID_NOT;
    camera_entity.think = camera_think;
    camera_entity.nextthink = time + 0.1;
    setorigin(camera_entity, CAMERA_REVIEW_POS);
    camera_entity.angles = camera_look_angles(CAMERA_REVIEW_POS, CAMERA_REVIEW_TARGET);
    camera_phase = 0;
};
