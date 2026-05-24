// Screwm CSQC - minimal DarkPlaces client-side definitions.
// The system globals/fields before end_sys_* must match DarkPlaces dpdefs order.

entity self;
entity other;
entity world;
float time;
float frametime;

float player_localentnum;
float player_localnum;
float maxclients;

float clientcommandframe;
float servercommandframe;

string mapname;

vector v_forward;
vector v_up;
vector v_right;

float trace_allsolid;
float trace_startsolid;
float trace_fraction;
vector trace_endpos;
vector trace_plane_normal;
float trace_plane_dist;
entity trace_ent;
float trace_inopen;
float trace_inwater;

void(float apilevel, string enginename, float engineversion) CSQC_Init;
void() CSQC_Shutdown;
float(float evtype, float scanx, float chary) CSQC_InputEvent;
void(float vid_width, float vid_height, float notmenu) CSQC_UpdateView;
float(string cmdstr) CSQC_ConsoleCommand;

vector pmove_org;
vector pmove_vel;
vector pmove_mins;
vector pmove_maxs;
float input_timelength;
vector input_angles;
vector input_movevalues;
float input_buttons;

float movevar_gravity;
float movevar_stopspeed;
float movevar_maxspeed;
float movevar_spectatormaxspeed;
float movevar_accelerate;
float movevar_airaccelerate;
float movevar_wateraccelerate;
float movevar_friction;
float movevar_waterfriction;
float movevar_entgravity;

void end_sys_globals;

.float modelindex;
.vector absmin, absmax;
.float entnum;
.float drawmask;
.void() predraw;
.float movetype;
.float solid;
.vector origin;
.vector oldorigin;
.vector velocity;
.vector angles;
.vector avelocity;
.string classname;
.string model;
.float frame;
.float skin;
.float effects;
.vector mins, maxs;
.vector size;
.void() touch;
.void() use;
.void() think;
.void() blocked;
.float nextthink;
.entity chain;
.string netname;
.entity enemy;
.float flags;
.float colormap;
.entity owner;

void end_sys_fields;

float intermission;
vector view_angles;
vector view_punchangle;
vector view_punchvector;

const float MASK_ENGINE = 1;
const float MASK_ENGINEVIEWMODELS = 2;
const float MASK_NORMAL = 4;

const float VF_DRAWWORLD = 19;
const float VF_DRAWENGINESBAR = 20;
const float VF_DRAWCROSSHAIR = 21;

const float DRAWFLAG_NORMAL = 0;
const float DRAWFLAG_ADDITIVE = 1;
const float DRAWFLAG_MODULATE = 2;
const float DRAWFLAG_2XMODULATE = 3;

const float TRUE = 1;
const float FALSE = 0;
const vector VEC_0 = '0 0 0';
const vector VEC_1 = '1 1 1';

float FILE_READ = 0;

float(string s) cvar = #45;
string(float f) ftos = #26;
float(string s) stof = #81;
float(float v) sin = #60;
float(float v) cos = #61;
string(string a, string b) strcat = #115;

float(string filename, float mode) fopen = #110;
void(float fhandle) fclose = #111;
string(float fhandle) fgets = #112;

void() clearscene = #300;
void(float mask) addentities = #301;
float(float property, ...) setproperty = #303;
void() renderscene = #304;
void(vector org, float radius, vector lightcolours) adddynamiclight = #305;
vector(vector v) cs_project = #311;
void(float width, vector pos1, vector pos2, vector rgb, float alpha, float drawflag) drawline = #315;
float(vector position, string text, vector scale, vector rgb, float alpha, float flag) drawstring = #321;
float(vector position, vector size, vector rgb, float alpha, float flag) drawfill = #323;
