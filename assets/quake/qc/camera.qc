// Screwm QuakeC — pendulum camera with Catmull-Rom interpolation

entity camera_entity;
float camera_phase;

vector catmull_rom(vector p0, vector p1, vector p2, vector p3, float t)
{
    float t2 = t * t;
    float t3 = t2 * t;

    float a0 = -0.5 * t3 + t2 - 0.5 * t;
    float a1 = 1.5 * t3 - 2.5 * t2 + 1.0;
    float a2 = -1.5 * t3 + 2.0 * t2 + 0.5 * t;
    float a3 = 0.5 * t3 - 0.5 * t2;

    vector result;
    result_x = a0 * p0_x + a1 * p1_x + a2 * p2_x + a3 * p3_x;
    result_y = a0 * p0_y + a1 * p1_y + a2 * p2_y + a3 * p3_y;
    result_z = a0 * p0_z + a1 * p1_z + a2 * p2_z + a3 * p3_z;
    return result;
};

vector get_station(float idx)
{
    if (idx <= 0) return STATION_0;
    if (idx <= 1) return STATION_1;
    if (idx <= 2) return STATION_2;
    if (idx <= 3) return STATION_3;
    if (idx <= 4) return STATION_4;
    return STATION_5;
};

vector spline_position(float phase)
{
    float seg_count = 5;
    float t_total = phase * seg_count;
    float seg = floor(t_total);
    float t = t_total - seg;

    if (seg >= seg_count) seg = seg_count - 1;

    float i0 = seg - 1;
    float i1 = seg;
    float i2 = seg + 1;
    float i3 = seg + 2;

    if (i0 < 0) i0 = 0;
    if (i3 > 5) i3 = 5;

    return catmull_rom(
        get_station(i0),
        get_station(i1),
        get_station(i2),
        get_station(i3),
        t
    );
};

void() camera_think =
{
    camera_phase = camera_phase + frametime / CAMERA_PERIOD;
    if (camera_phase >= 1.0)
        camera_phase = camera_phase - 1.0;

    // Smoothstep speed remapping for gentle acceleration/deceleration
    float phase = camera_phase;
    float smooth = phase * phase * (3.0 - 2.0 * phase);

    vector pos = spline_position(smooth);
    setorigin(self, pos);

    // Look toward AoA center using makevectors approach
    vector look_dir = AOA_CENTER - pos;
    vector ang;
    ang_y = vectoyaw(look_dir);
    // Pitch: vertical angle toward target (positive = down in Quake)
    float hdist = sqrt(look_dir_x * look_dir_x + look_dir_y * look_dir_y);
    if (hdist > 0.01)
        ang_x = 0 - (look_dir_z / hdist) * 45.0; // approximate pitch
    else
        ang_x = 0;
    ang_z = 0;
    self.angles = ang;

    self.nextthink = time + 0.033; // ~30fps
};

void() spawn_camera =
{
    camera_entity = spawn();
    camera_entity.classname = "camera";
    camera_entity.movetype = MOVETYPE_NONE;
    camera_entity.solid = SOLID_NOT;
    camera_entity.think = camera_think;
    camera_entity.nextthink = time + 0.1;
    setorigin(camera_entity, STATION_0);
    camera_phase = 0;
};
