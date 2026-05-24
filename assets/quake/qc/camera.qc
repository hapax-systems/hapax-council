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

vector() camera_file_target =
{
    vector target;
    float pan_x;
    float pan_y;
    float target_z_norm;

    pan_x = camera_read_norm("data/camera-pan-x.txt", 0.5);
    pan_y = camera_read_norm("data/camera-pan-y.txt", 0.5);
    target_z_norm = camera_read_norm("data/camera-target-z.txt", 0.475);

    target = CAMERA_REVIEW_TARGET;
    target_x = target_x + (pan_x - 0.5) * 160;
    target_y = target_y + (pan_y - 0.5) * 120;
    target_z = 40 + target_z_norm * 240;
    return target;
};

vector(vector target) camera_file_position =
{
    vector pos;
    float yaw_norm;
    float dist_norm;
    float height_norm;
    float yaw;
    float dist;

    yaw_norm = camera_read_norm("data/camera-yaw.txt", 0.5);
    dist_norm = camera_read_norm("data/camera-distance.txt", 0.54);
    height_norm = camera_read_norm("data/camera-height.txt", 0.384);

    yaw = (yaw_norm - 0.5) * 2.2;
    dist = 150 + dist_norm * 190;

    pos_x = target_x + sin(yaw) * dist;
    pos_y = target_y - cos(yaw) * dist;
    pos_z = 58 + height_norm * 250;
    return pos;
};

void() camera_apply_file_fov =
{
    float fov_norm;
    float fov_value;

    fov_norm = camera_read_norm("data/camera-fov.txt", 0.78);
    fov_value = 55 + fov_norm * 45;
    localcmd(strcat(strcat("fov ", ftos(fov_value)), "\n"));
};

void() camera_think =
{
    vector pos;
    vector target;

    target = CAMERA_REVIEW_TARGET;
    if (
        cvar("screwm_camera_file_control") > 0
        && camera_read_norm("data/camera-manual.txt", 0) > 0
    )
    {
        target = camera_file_target();
        pos = camera_file_position(target);
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
