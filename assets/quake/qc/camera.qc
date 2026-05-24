// Screwm QuakeC — stable review camera with optional slow orbit

float camera_phase;

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

void() camera_think =
{
    vector pos;
    vector target;

    target = CAMERA_REVIEW_TARGET;
    if (cvar("screwm_camera_orbit") > 0)
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
