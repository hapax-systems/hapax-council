// Screwm QuakeC — shared definitions
// Minimal progs for tower camera + AoA rotation + ambient sound

entity self;
entity world;
entity other;

float time;
float frametime;

// Builtins
void(vector ang) makevectors = #1;
void(entity e, string m) setmodel = #3;
float(vector v) vlen = #12;
float(vector v) vectoyaw = #13;
entity() spawn = #14;
void(entity e) remove = #15;
void(entity e, vector o) setorigin = #2;
void(entity e, float chan, string samp, float vol, float attn) sound = #8;
string(float f) ftos = #26;
string(vector v) vtos = #27;
void(string s) dprint = #25;
float(string s) cvar = #45;
void(string var, string val) cvar_set = #72;
float(string s) stof = #81;
float(float v) rint = #36;
float(float v) floor = #37;
float(float v) sin = #60;
float(float v) cos = #61;
float(float v) sqrt = #62;
float(float v) fabs = #43;
// asin not a Quake builtin — approximate in camera.qc
void(float to, float f) WriteByte = #52;
void(float to, entity e) WriteEntity = #59;
// etos not needed for camera-only mod
void(string s) precache_model = #20;
void(string s) precache_sound = #19;

// File I/O (DarkPlaces extension)
float(string filename, float mode) fopen = #110;
void(float fhandle) fclose = #111;
string(float fhandle) fgets = #112;

float FILE_READ = 0;

// Message destinations
float MSG_BROADCAST = 2;
float MSG_ONE = 1;
entity msg_entity;

// Constants
float MOVETYPE_NONE = 0;
float SOLID_NOT = 0;
float SOUNDFLAG_FORCELOOP = 1;

// Entity fields
.string classname;
.float nextthink;
.void() think;
.string model;
.vector origin;
.vector angles;
.float movetype;
.float solid;
.vector avelocity;
.float effects;

// Spline control points (Quake units, 32u = 1m)
// Matches scene.rs SPIRAL_STATIONS
vector STATION_0 = '0 -32 120';
vector STATION_1 = '80 64 80';
vector STATION_2 = '-60 160 100';
vector STATION_3 = '40 256 -80';
vector STATION_4 = '-40 352 60';
vector STATION_5 = '0 -32 120';

vector AOA_CENTER = '0 176 0';

float CAMERA_PERIOD = 135;

// Required entry points for DarkPlaces
void() StartFrame;
void() PlayerPreThink;
void() PlayerPostThink;
void() ClientKill;
void() ClientConnect;
void() PutClientInServer;
void() ClientDisconnect;
void() SetNewParms;
void() SetChangeParms;
