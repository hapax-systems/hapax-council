// Screwm QuakeC — world initialization, AoA entity, ambient sound

entity aoa_entity;

void() aoa_think =
{
    self.angles_y = self.angles_y + frametime * 15;
    if (self.angles_y >= 360)
        self.angles_y = self.angles_y - 360;
    self.nextthink = time + 0.033;
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
    aoa_entity.avelocity = '0 15 0';
    // Model set via setmodel if MDL available
    // setmodel(aoa_entity, "progs/aoa.mdl");
};

void() spawn_ambient_sounds =
{
    // Perception level (y -64 to 32)
    entity snd = spawn();
    snd.classname = "ambient_perception";
    setorigin(snd, '0 -16 0');
    // sound(snd, 1, "ambient/perception_rumble.ogg", 0.6, 3);

    // Cognition level (y 32 to 128)
    snd = spawn();
    snd.classname = "ambient_cognition";
    setorigin(snd, '0 80 0');

    // Communication level (y 128 to 224)
    snd = spawn();
    snd.classname = "ambient_communication";
    setorigin(snd, '0 176 0');

    // Expression level (y 224 to 320)
    snd = spawn();
    snd.classname = "ambient_expression";
    setorigin(snd, '0 272 0');

    // Grounding level (y 320 to 416)
    snd = spawn();
    snd.classname = "ambient_grounding";
    setorigin(snd, '0 368 0');
};

void() worldspawn =
{
    // Precache models
    // precache_model("progs/aoa.mdl");

    // Precache sounds
    // precache_sound("ambient/perception_rumble.ogg");
    // precache_sound("ambient/cognition_clicks.ogg");
    // precache_sound("ambient/communication_static.ogg");
    // precache_sound("ambient/expression_synth.ogg");
    // precache_sound("ambient/grounding_drone.ogg");

    spawn_camera();
    spawn_aoa();
    spawn_ambient_sounds();
};
