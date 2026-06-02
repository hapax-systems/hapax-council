// Screwm QuakeC — world initialization, AoA entity, ambient sound

// aoa_entity declared in defs.qc

void() aoa_think =
{
    self.angles_y = self.angles_y + frametime * self.screwm_spin_y;
    if (self.angles_y >= 360)
        self.angles_y = self.angles_y - 360;
    self.nextthink = time + 0.0139;
};

void(entity ent) aoa_common_visuals =
{
    ent.movetype = MOVETYPE_NONE;
    ent.solid = SOLID_NOT;
    setorigin(ent, AOA_CENTER);
    ent.angles_y = 180;
    ent.think = aoa_think;
    ent.nextthink = time + 0.1;
    ent.screwm_spin_y = 0;
    ent.effects = EF_DOUBLESIDED + EF_DYNAMICMODELLIGHT;
};

void() spawn_aoa =
{
    aoa_entity = spawn();
    aoa_entity.classname = "aoa";
    aoa_common_visuals(aoa_entity);
    setmodel(aoa_entity, "progs/aoa.mdl");
    aoa_entity.scale = AOA_MODEL_SCALE;
    aoa_entity.alpha = 0.16;
    // Cool near-neutral tint (was saturated pink) so the AoA reads as a
    // desaturated luminous-edge body, not a magenta fill. Per-facet hue now comes
    // (subtly) from the desaturated atlas fill, not a global pink colormod.
    aoa_entity.colormod = '0.86 0.92 1.02';
    aoa_entity.glowmod = '0.60 0.66 0.76';
    aoa_entity.glow_color = 236;
    aoa_entity.glow_size = 0;
    aoa_entity.glow_trail = 0;
    aoa_entity.effects = aoa_entity.effects + EF_ADDITIVE;

    aoa_sphere_entity = spawn();
    aoa_sphere_entity.classname = "aoa_media_sphere";
    aoa_common_visuals(aoa_sphere_entity);
    setorigin(aoa_sphere_entity, AOA_SPHERE_CENTER);
    setmodel(aoa_sphere_entity, "progs/aoa_sphere.mdl");
    aoa_sphere_entity.scale = AOA_SPHERE_MODEL_SCALE;
    aoa_sphere_entity.alpha = 1.0;
    aoa_sphere_entity.colormod = '1.0 1.0 1.0';
    aoa_sphere_entity.glowmod = '0.35 0.25 0.10';
    aoa_sphere_entity.glow_color = 236;
    aoa_sphere_entity.glow_size = 0;
    aoa_sphere_entity.screwm_spin_y = 0;
};

void() spawn_ambient_sounds =
{
    entity snd;

    snd = spawn();
    snd.classname = "ambient_perception";
    setorigin(snd, '0 0 -16');
    sound(snd, 1, "ambient/perception.ogg", 0.5, 0);

    snd = spawn();
    snd.classname = "ambient_cognition";
    setorigin(snd, '0 0 80');
    sound(snd, 1, "ambient/cognition.ogg", 0.4, 0);

    snd = spawn();
    snd.classname = "ambient_communication";
    setorigin(snd, '0 0 176');
    sound(snd, 1, "ambient/communication.ogg", 0.35, 0);

    snd = spawn();
    snd.classname = "ambient_expression";
    setorigin(snd, '0 0 272');
    sound(snd, 1, "ambient/expression.ogg", 0.3, 0);

    snd = spawn();
    snd.classname = "ambient_grounding";
    setorigin(snd, '0 0 368');
    sound(snd, 1, "ambient/grounding.ogg", 0.45, 0);
};

void() StartFrame =
{
    coupling_tick();
};

void(entity view) screwm_free_view_body =
{
    view.movetype = MOVETYPE_NOCLIP;
    view.solid = SOLID_NOT;
    view.velocity = '0 0 0';
    view.avelocity = '0 0 0';
};

void(entity view) screwm_player_noclip_body =
{
    view.movetype = MOVETYPE_NOCLIP;
    view.solid = SOLID_NOT;
    view.avelocity = '0 0 0';
};

void(entity view) screwm_follow_camera_body =
{
    screwm_free_view_body(view);
    setorigin(view, camera_entity.origin);
    view.angles = camera_entity.angles;
    view.fixangle = 1;
};

void() PlayerPreThink =
{
    if (
        camera_entity
        && cvar("screwm_csqc_review_camera") > 0
        && camera_read_norm("data/camera-manual.txt", 0) > 0
    )
    {
        screwm_follow_camera_body(self);
        return;
    }

    if (cvar("screwm_player_noclip_control") > 0)
    {
        screwm_player_noclip_body(self);
        return;
    }

    if (cvar("screwm_csqc_review_camera") > 0)
    {
        screwm_free_view_body(self);
        return;
    }

    if (camera_entity)
    {
        screwm_follow_camera_body(self);
    }
};
void() PlayerPostThink = {};
void() ClientKill = {};
void() ClientConnect = {};
void() PutClientInServer =
{
    screwm_free_view_body(self);
    setorigin(self, CAMERA_REVIEW_POS);
    self.angles = vectoangles(CAMERA_REVIEW_TARGET - CAMERA_REVIEW_POS);
    self.fixangle = 1;
};
void() ClientDisconnect = {};
void() SetNewParms = {};
void() SetChangeParms = {};

void() worldspawn =
{
    precache_model("progs/aoa.mdl");
    precache_model("progs/aoa_sphere.mdl");

    precache_sound("ambient/perception.ogg");
    precache_sound("ambient/cognition.ogg");
    precache_sound("ambient/communication.ogg");
    precache_sound("ambient/expression.ogg");
    precache_sound("ambient/grounding.ogg");

    coupling_init();
    spawn_camera();
    spawn_aoa();
    spawn_ambient_sounds();
};
