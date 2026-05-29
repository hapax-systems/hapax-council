// Screwm QuakeC — world initialization, AoA entity, ambient sound

// aoa_entity declared in defs.qc

void() aoa_think =
{
    self.angles_y = self.angles_y + frametime * self.screwm_spin_y;
    if (self.angles_y >= 360)
        self.angles_y = self.angles_y - 360;
    self.nextthink = time + 0.0139;
};

void() spawn_aoa =
{
    aoa_entity = spawn();
    aoa_entity.classname = "aoa";
    aoa_entity.movetype = MOVETYPE_NONE;
    aoa_entity.solid = SOLID_NOT;
    setorigin(aoa_entity, AOA_CENTER);
    aoa_entity.think = aoa_think;
    aoa_entity.nextthink = time + 0.1;
    aoa_entity.screwm_spin_y = 3;
    setmodel(aoa_entity, "progs/aoa.mdl");
    aoa_entity.scale = AOA_MODEL_SCALE;
    aoa_entity.alpha = 0.62;
    aoa_entity.colormod = '1.35 0.92 0.36';
    aoa_entity.glowmod = '1.00 0.64 0.24';
    aoa_entity.glow_color = 236;
    aoa_entity.glow_size = 72;
    aoa_entity.glow_trail = 1;
    aoa_entity.effects = EF_FULLBRIGHT + EF_NOSHADOW + EF_DOUBLESIDED + EF_DYNAMICMODELLIGHT;
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

void() PlayerPreThink =
{
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
        screwm_free_view_body(self);
        setorigin(self, camera_entity.origin);
        self.angles = camera_entity.angles;
        self.fixangle = 1;
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
