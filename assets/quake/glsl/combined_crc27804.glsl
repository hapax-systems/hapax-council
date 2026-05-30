/* The engine may define the following macros:
#define VERTEX_SHADER
#define GEOMETRY_SHADER
#define FRAGMENT_SHADER
#define MODE_GENERIC
#define MODE_POSTPROCESS
#define MODE_DEPTH_OR_SHADOW
#define MODE_FLATCOLOR
#define MODE_VERTEXCOLOR
#define MODE_LIGHTMAP
#define MODE_LIGHTDIRECTIONMAP_MODELSPACE
#define MODE_LIGHTDIRECTIONMAP_TANGENTSPACE
#define MODE_LIGHTDIRECTIONMAP_FORCED_LIGHTMAP
#define MODE_LIGHTDIRECTIONMAP_FORCED_VERTEXCOLOR
#define MODE_LIGHTGRID
#define MODE_LIGHTDIRECTION
#define MODE_LIGHTSOURCE
#define MODE_REFRACTION
#define MODE_WATER
#define MODE_DEFERREDGEOMETRY
#define MODE_DEFERREDLIGHTSOURCE
#define USEDIFFUSE
#define USEVERTEXTEXTUREBLEND
#define USEVIEWTINT
#define USECOLORMAPPING
#define USESATURATION
#define USEFOGINSIDE
#define USEFOGOUTSIDE
#define USEFOGHEIGHTTEXTURE
#define USEFOGALPHAHACK
#define USEGAMMARAMPS
#define USECUBEFILTER
#define USEGLOW
#define USEBLOOM
#define USESPECULAR
#define USEPOSTPROCESSING
#define USEREFLECTION
#define USEOFFSETMAPPING
#define USEOFFSETMAPPING_RELIEFMAPPING
#define USESHADOWMAP2D
#define USESHADOWMAPVSDCT
#define USESHADOWMAPORTHO
#define USEDEFERREDLIGHTMAP
#define USEALPHAKILL
#define USEREFLECTCUBE
#define USENORMALMAPSCROLLBLEND
#define USEBOUNCEGRID
#define USEBOUNCEGRIDDIRECTIONAL
#define USETRIPPY
#define USEDEPTHRGB
#define USEALPHAGENVERTEX
#define USESKELETAL
#define USEOCCLUDE
*/
// ambient+diffuse+specular+normalmap+attenuation+cubemap+fog shader
// written by Ashley Rose Hale (LadyHavoc)
// shadowmapping enhancements by Lee 'eihrul' Salzman

#if defined(USESKELETAL) || defined(USEOCCLUDE)
#  ifdef GL_ARB_uniform_buffer_object
#    extension GL_ARB_uniform_buffer_object : enable
#  endif
#endif

#ifdef USESHADOWMAP2D
# ifdef GL_EXT_gpu_shader4
#   extension GL_EXT_gpu_shader4 : enable
# endif
# ifdef GL_ARB_texture_gather
#   extension GL_ARB_texture_gather : enable
# else
#   ifdef GL_AMD_texture_texture4
#     extension GL_AMD_texture_texture4 : enable
#   endif
# endif
#endif

#define sat(x) clamp(x, 0, 1)
#define possat(x) sat(x)
#define minonesat(x) sat(x)
#define possatdot(x, y) possat(dot(x, y))

#ifdef USECELSHADING
# define SHADEDIFFUSE myhalf diffuse = cast_myhalf(sat(float(dot(surfacenormal, lightnormal)) * 2.0));
# ifdef USEEXACTSPECULARMATH
#  define SHADESPECULAR(specpow) myhalf specular = pow(cast_myhalf(float(possatdot(reflect(lightnormal, surfacenormal), -eyenormal))), 1.0 + specpow);specular = possat(specular * 10.0 - 9.0);
# else
#  define SHADESPECULAR(specpow) myhalf3 specularnormal = normalize(lightnormal + eyenormal);myhalf specular = pow(cast_myhalf(float(possatdot(surfacenormal, specularnormal))), 1.0 + specpow);specular = possat(specular * 10.0 - 9.0);
# endif
#else
# define SHADEDIFFUSE myhalf diffuse = cast_myhalf(float(possatdot(surfacenormal, lightnormal)));
# ifdef USEEXACTSPECULARMATH
#  define SHADESPECULAR(specpow) myhalf specular = pow(cast_myhalf(float(possatdot(reflect(lightnormal, surfacenormal), -eyenormal))), 1.0 + specpow);
# else
#  define SHADESPECULAR(specpow) myhalf3 specularnormal = normalize(lightnormal + eyenormal);myhalf specular = pow(cast_myhalf(float(possatdot(surfacenormal, specularnormal))), 1.0 + specpow);
# endif
#endif

#if (defined(GLSL120) || defined(GLSL130) || defined(GLSL140) || defined(GLES)) && defined(VERTEX_SHADER)

invariant gl_Position; // fix for lighting polygons not matching base surface
# endif
#if defined(GLSL130) || defined(GLSL140)
precision highp float;
# ifdef VERTEX_SHADER
#  define dp_varying out
#  define dp_attribute in
# endif
# ifdef FRAGMENT_SHADER
out vec4 dp_FragColor;
#  define dp_varying in
#  define dp_attribute in
# endif
# define dp_offsetmapping_dFdx dFdx
# define dp_offsetmapping_dFdy dFdy
# define dp_textureGrad textureGrad
# define dp_textureOffset(a,b,c,d) textureOffset(a,b,ivec2(c,d))
# define dp_texture2D texture
# define dp_texture3D texture
# define dp_textureCube texture
# define dp_shadow2D(a,b) float(texture(a,b))
#else
# ifdef FRAGMENT_SHADER
#  define dp_FragColor gl_FragColor
# endif
# define dp_varying varying
# define dp_attribute attribute
# define dp_offsetmapping_dFdx(a) vec2(0.0, 0.0)
# define dp_offsetmapping_dFdy(a) vec2(0.0, 0.0)
# define dp_textureGrad(a,b,c,d) texture2D(a,b)
# define dp_textureOffset(a,b,c,d) texture2DOffset(a,b,ivec2(c,d))
# define dp_texture2D texture2D
# define dp_texture3D texture3D
# define dp_textureCube textureCube
# define dp_shadow2D(a,b) float(shadow2D(a,b))
#endif

// GL ES and GLSL130 shaders use precision modifiers, standard GL does not
// in GLSL130 we don't use them though because of syntax differences (can't use precision with inout)
#ifndef GL_ES
#define lowp
#define mediump
#define highp
#endif

#ifdef USEDEPTHRGB
	// for 565 RGB we'd need to use different multipliers
#define decodedepthmacro(d) dot((d).rgb, vec3(1.0, 255.0 / 65536.0, 255.0 / 16777215.0))
#define encodedepthmacro(d) fract(vec4(d, d*256.0, d*65536.0, 0.0))
#endif

#ifdef VERTEX_SHADER
dp_attribute vec4 Attrib_Position;  // vertex
dp_attribute vec4 Attrib_Color;     // color
dp_attribute vec4 Attrib_TexCoord0; // material texcoords
dp_attribute vec3 Attrib_TexCoord1; // svector
dp_attribute vec3 Attrib_TexCoord2; // tvector
dp_attribute vec3 Attrib_TexCoord3; // normal
dp_attribute vec4 Attrib_TexCoord4; // lightmap texcoords
#ifdef USESKELETAL
//uniform mat4 Skeletal_Transform[128];
// this is used with glBindBufferRange to bind a uniform block to the name
// Skeletal_Transform12_UniformBlock, the Skeletal_Transform12 variable is
// directly accessible without a namespace.
// explanation: http://www.opengl.org/wiki/Interface_Block_%28GLSL%29#Syntax
uniform Skeletal_Transform12_UniformBlock
{
	vec4 Skeletal_Transform12[768];
};
dp_attribute vec4 Attrib_SkeletalIndex;
dp_attribute vec4 Attrib_SkeletalWeight;
#endif
#endif
dp_varying mediump vec4 VertexColor;

#if defined(USEFOGINSIDE) || defined(USEFOGOUTSIDE) || defined(USEFOGHEIGHTTEXTURE)
# define USEFOG
#endif
#if defined(MODE_LIGHTMAP) || defined(MODE_LIGHTDIRECTIONMAP_MODELSPACE) || defined(MODE_LIGHTDIRECTIONMAP_TANGENTSPACE) || defined(MODE_LIGHTDIRECTIONMAP_FORCED_LIGHTMAP)
# define USELIGHTMAP
#endif
#if defined(USESPECULAR) || defined(USEOFFSETMAPPING) || defined(USEREFLECTCUBE) || defined(USEFOG)
# define USEEYEVECTOR
#endif

//#ifdef __GLSL_CG_DATA_TYPES
//# define myhalf half
//# define myhalf2 half2
//# define myhalf3 half3
//# define myhalf4 half4
//# define cast_myhalf half
//# define cast_myhalf2 half2
//# define cast_myhalf3 half3
//# define cast_myhalf4 half4
//#else
# define myhalf mediump float
# define myhalf2 mediump vec2
# define myhalf3 mediump vec3
# define myhalf4 mediump vec4
# define cast_myhalf float
# define cast_myhalf2 vec2
# define cast_myhalf3 vec3
# define cast_myhalf4 vec4
//#endif

#ifdef VERTEX_SHADER
uniform highp mat4 ModelViewProjectionMatrix;
#endif

#ifdef VERTEX_SHADER
#ifdef USETRIPPY
// LadyHavoc: based on shader code linked at: http://www.youtube.com/watch?v=JpksyojwqzE
// tweaked scale
uniform highp float ClientTime;
vec4 TrippyVertex(vec4 position)
{
	float worldTime = ClientTime;
	// tweaked for Quake
	worldTime *= 10.0;
	position *= 0.125;
	//~tweaked for Quake
	float distanceSquared = (position.x * position.x + position.z * position.z);
	position.y += 5.0*sin(distanceSquared*sin(worldTime/143.0)/1000.0);
	float y = position.y;
	float x = position.x;
	float om = sin(distanceSquared*sin(worldTime/256.0)/5000.0) * sin(worldTime/200.0);
	position.y = x*sin(om)+y*cos(om);
	position.x = x*cos(om)-y*sin(om);
	return position;
}
#endif
#endif

#ifdef MODE_DEPTH_OR_SHADOW
#ifdef VERTEX_SHADER
void main(void)
{
#ifdef USESKELETAL
	ivec4 si0 = ivec4(Attrib_SkeletalIndex * 3.0);
	ivec4 si1 = si0 + ivec4(1, 1, 1, 1);
	ivec4 si2 = si0 + ivec4(2, 2, 2, 2);
	vec4 sw = Attrib_SkeletalWeight;
	vec4 SkeletalMatrix1 = Skeletal_Transform12[si0.x] * sw.x + Skeletal_Transform12[si0.y] * sw.y + Skeletal_Transform12[si0.z] * sw.z + Skeletal_Transform12[si0.w] * sw.w;
	vec4 SkeletalMatrix2 = Skeletal_Transform12[si1.x] * sw.x + Skeletal_Transform12[si1.y] * sw.y + Skeletal_Transform12[si1.z] * sw.z + Skeletal_Transform12[si1.w] * sw.w;
	vec4 SkeletalMatrix3 = Skeletal_Transform12[si2.x] * sw.x + Skeletal_Transform12[si2.y] * sw.y + Skeletal_Transform12[si2.z] * sw.z + Skeletal_Transform12[si2.w] * sw.w;
	mat4 SkeletalMatrix = mat4(SkeletalMatrix1, SkeletalMatrix2, SkeletalMatrix3, vec4(0.0, 0.0, 0.0, 1.0));
	vec4 SkeletalVertex = Attrib_Position * SkeletalMatrix;
#define Attrib_Position SkeletalVertex
#endif
	gl_Position = ModelViewProjectionMatrix * Attrib_Position;
#ifdef USETRIPPY
	gl_Position = TrippyVertex(gl_Position);
#endif
}
#endif

#ifdef FRAGMENT_SHADER
void main(void)
{
#ifdef USEDEPTHRGB
	dp_FragColor = encodedepthmacro(gl_FragCoord.z);
#else
	dp_FragColor = vec4(1.0,1.0,1.0,1.0);
#endif
}
#endif
#else // !MODE_DEPTH_ORSHADOW




#ifdef MODE_POSTPROCESS
#ifdef USEBLOOM
dp_varying mediump vec4 TexCoord1;
#else
dp_varying mediump vec2 TexCoord1;
#endif

#ifdef VERTEX_SHADER
void main(void)
{
	gl_Position = ModelViewProjectionMatrix * Attrib_Position;
	TexCoord1.xy = Attrib_TexCoord0.xy;
#ifdef USEBLOOM
	TexCoord1.zw = Attrib_TexCoord4.xy;
#endif
}
#endif

#ifdef FRAGMENT_SHADER
uniform sampler2D Texture_First;
#ifdef USEBLOOM
uniform sampler2D Texture_Second;
uniform mediump vec4 BloomColorSubtract;
#endif
#ifdef USEGAMMARAMPS
uniform sampler2D Texture_GammaRamps;
#endif
#ifdef USESATURATION
uniform mediump float Saturation;
#endif
#ifdef USEVIEWTINT
uniform mediump vec4 ViewTintColor;
#endif
//uncomment these if you want to use them:
uniform mediump vec4 UserVec1;
uniform mediump vec4 UserVec2;
uniform mediump vec4 UserVec3;
uniform mediump vec4 UserVec4;
uniform mediump float ColorFringe;
uniform highp float ClientTime;
uniform mediump vec2 PixelSize;

#ifdef USEFXAA
// graphitemaster: based off the white paper by Timothy Lottes
// http://developer.download.nvidia.com/assets/gamedev/files/sdk/11/FXAA_WhitePaper.pdf
vec4 fxaa(vec4 inColor, float maxspan)
{
	vec4 ret = inColor; // preserve old
	float mulreduct = 1.0/maxspan;
	float minreduct = (1.0 / 128.0);

	// directions
	vec3 NW = dp_texture2D(Texture_First, TexCoord1.xy + (vec2(-1.0, -1.0) * PixelSize)).xyz;
	vec3 NE = dp_texture2D(Texture_First, TexCoord1.xy + (vec2(+1.0, -1.0) * PixelSize)).xyz;
	vec3 SW = dp_texture2D(Texture_First, TexCoord1.xy + (vec2(-1.0, +1.0) * PixelSize)).xyz;
	vec3 SE = dp_texture2D(Texture_First, TexCoord1.xy + (vec2(+1.0, +1.0) * PixelSize)).xyz;
	vec3 M = dp_texture2D(Texture_First, TexCoord1.xy).xyz;

	// luminance directions
	vec3 luma = vec3(0.299, 0.587, 0.114);
	float lNW = dot(NW, luma);
	float lNE = dot(NE, luma);
	float lSW = dot(SW, luma);
	float lSE = dot(SE, luma);
	float lM = dot(M, luma);
	float lMin = min(lM, min(min(lNW, lNE), min(lSW, lSE)));
	float lMax = max(lM, max(max(lNW, lNE), max(lSW, lSE)));

	// direction and reciprocal
	vec2 dir = vec2(-((lNW + lNE) - (lSW + lSE)), ((lNW + lSW) - (lNE + lSE)));
	float rcp = 1.0/(min(abs(dir.x), abs(dir.y)) + max((lNW + lNE + lSW + lSE) * (0.25 * mulreduct), minreduct));

	// span
	dir = min(vec2(maxspan, maxspan), max(vec2(-maxspan, -maxspan), dir * rcp)) * PixelSize;

	vec3 rA = (1.0/2.0) * (
		dp_texture2D(Texture_First, TexCoord1.xy + dir * (1.0/3.0 - 0.5)).xyz +
		dp_texture2D(Texture_First, TexCoord1.xy + dir * (2.0/3.0 - 0.5)).xyz);
	vec3 rB = rA * (1.0/2.0) + (1.0/4.0) * (
		dp_texture2D(Texture_First, TexCoord1.xy + dir * (0.0/3.0 - 0.5)).xyz +
		dp_texture2D(Texture_First, TexCoord1.xy + dir * (3.0/3.0 - 0.5)).xyz);
	float lB = dot(rB, luma);

	ret.xyz = ((lB < lMin) || (lB > lMax)) ? rA : rB;
	ret.a = 1.0;
	return ret;
}
#endif

void main(void)
{
#ifdef USECOLORFRINGE
	float fringe = ColorFringe;//.0033f;
	float amount = distance(TexCoord1.xy, vec2(.5f,.5f));
	vec2 offset = vec2(amount*fringe,amount*fringe);
	dp_FragColor.xy = dp_texture2D(Texture_First, TexCoord1.xy-offset).xy;
	dp_FragColor.z = dp_texture2D(Texture_First, TexCoord1.xy+offset).z;
#else
	dp_FragColor = dp_texture2D(Texture_First, TexCoord1.xy);
#endif

#ifdef USEFXAA
	dp_FragColor = fxaa(dp_FragColor, 8.0); // 8.0 can be changed for larger span
#endif

#ifdef USEPOSTPROCESSING
// Screwm/Scroom post-processing — entity-local drift/compositing field.
// UserVec1: x=room_absorption, y=prismatic_drift, z=temperature_bias, w=dust
// UserVec2: x=signal_aura, y=edge_glow, z=posterize_levels, w=sharpen
// UserVec3: x=spatial_warp, y=signal_noise, z=halftone_size, w=threshold
// UserVec4: x=surface_emboss/kaleidoscope, y=invert_mix, z=circular_mask_r, w=thermal_mix
// Effects run unconditionally — UserVec uniforms always available
	vec2 uv = TexCoord1.xy;
	vec2 px = PixelSize;

	// === UV DISTORTION PHASE (before color sampling) ===

	// Mirror (toggle via sign of fisheye: negative = mirror X)
	if (UserVec3.x < -0.001) {
		uv.x = 1.0 - uv.x;
	}

	// Fisheye lens distortion (positive values)
	float fisheye_val = abs(UserVec3.x);
	if (fisheye_val > 0.001) {
		vec2 fc = uv - vec2(0.5);
		float r2 = dot(fc, fc);
		uv = fc * (1.0 + fisheye_val * r2) + vec2(0.5);
		uv = clamp(uv, vec2(0.0), vec2(1.0));
	}

	// Kaleidoscope (when UserVec4.x < -1.0, segments = abs(UserVec4.x))
	float kscope_seg = UserVec4.x;
	if (kscope_seg < -1.0) {
		float segments = abs(kscope_seg);
		vec2 kc = uv - vec2(0.5);
		float angle = atan(kc.y, kc.x);
		float radius = length(kc);
		float seg_angle = 6.28318 / segments;
		angle = mod(angle, seg_angle);
		if (angle > seg_angle * 0.5) angle = seg_angle - angle;
		uv = vec2(cos(angle), sin(angle)) * radius + vec2(0.5);
		uv = clamp(uv, vec2(0.0), vec2(1.0));
	}

	// UserVec4.x positive values are reserved for material emboss. Earlier
	// builds also rotated UVs here, which made review captures feel like camera
	// lurch even when the noclip camera was fixed.

	// === COLOR SAMPLING ===
	vec3 color = dp_texture2D(Texture_First, uv).rgb;
	float signal_luma = dot(color, vec3(0.299, 0.587, 0.114));
	float signal_presence = smoothstep(0.055, 0.30, signal_luma);

	// Entity-field chroma drift. This is the DarkPlaces side of the aggregate:
	// a subtle compositor-like separation that binds BSP, MDL, and live media
	// into one field instead of leaving Quake textures visually sovereign.
	float drift_phase = ClientTime * 0.11;
	vec2 drift_dir = normalize(vec2(sin(drift_phase + uv.y * 4.0), cos(drift_phase + uv.x * 3.0)));
	float drift_amt = clamp(UserVec1.y * 0.0048 + UserVec3.y * 0.014, 0.0, 0.018);
	vec3 drift_plus = dp_texture2D(Texture_First, clamp(uv + drift_dir * drift_amt, vec2(0.0), vec2(1.0))).rgb;
	vec3 drift_minus = dp_texture2D(Texture_First, clamp(uv - drift_dir * drift_amt, vec2(0.0), vec2(1.0))).rgb;
	color = mix(color, vec3(drift_plus.r, color.g, drift_minus.b), clamp(UserVec1.y * 0.42, 0.0, 0.70));
	color += (drift_plus * vec3(0.03, 0.14, 0.18) + drift_minus * vec3(0.17, 0.04, 0.13)) * clamp(UserVec3.y * 2.6, 0.0, 0.18);

	// Scroom feedback veil — a bounded echo of nearby frame samples. This is
	// not temporal accumulation yet; it approximates the old compositor drift
	// by making bright in-world signals leave a spatial color wake.
	float feedback_str = clamp(UserVec1.y * 0.070 + UserVec3.y * 0.82, 0.0, 0.18);
	vec2 feedback_offset = vec2(
		sin(ClientTime * 0.11 + uv.y * 8.0),
		cos(ClientTime * 0.09 + uv.x * 7.0)
	) * (0.006 + UserVec1.y * 0.006);
	vec3 feedback_a = dp_texture2D(Texture_First, clamp(uv + feedback_offset, vec2(0.0), vec2(1.0))).rgb;
	vec3 feedback_b = dp_texture2D(Texture_First, clamp(uv - feedback_offset * 1.7, vec2(0.0), vec2(1.0))).rgb;
	vec3 feedback_tint = feedback_a * vec3(0.60, 1.02, 1.18) + feedback_b * vec3(1.10, 0.54, 0.92);
	color = mix(color, max(color, feedback_tint * 0.68), feedback_str);

	// All effects operate on the WORLD, not the camera.
	// Lens-origin effects reframed as spatial phenomena.

	// 1. Entity absorption. No camera vignette or fourth-wall fog: absorption
	// binds only to nonblack world/media signal.
	float atmo_str = UserVec1.x;
	vec3 absorption_tint = mix(vec3(0.80, 0.92, 1.04), vec3(1.04, 0.78, 1.02), smoothstep(0.05, 0.95, uv.x));
	color = mix(color, color * absorption_tint, clamp(atmo_str * 0.20 * signal_presence, 0.0, 0.18));

	// 2. Prismatic entity refraction. The split rides signal edges and drift
	// direction; it is not a lens effect attached to the camera frame.
	float refract_amount = UserVec1.y * 0.0024 * signal_presence;
	vec2 refract_offset = drift_dir * refract_amount;
	color.r = dp_texture2D(Texture_First, uv + refract_offset).r;
	color.b = dp_texture2D(Texture_First, uv - refract_offset).b;

	// 3. Temperature bias — signal-bound only; no full-frame grade.
	float temp = UserVec1.z;
	color.r *= 1.0 + temp * 0.10 * signal_presence;
	color.g *= 1.0 + temp * 0.03 * signal_presence;
	color.b *= 1.0 - temp * 0.05 * signal_presence;

	// 4. Edge glow — Sobel edge detection with color tint
	float edge_str = UserVec2.y;
	if (edge_str > 0.001) {
		vec3 sx1 = dp_texture2D(Texture_First, uv + vec2(-px.x, px.y)).rgb;
		vec3 sx2 = dp_texture2D(Texture_First, uv + vec2(-px.x, 0.0)).rgb;
		vec3 sx3 = dp_texture2D(Texture_First, uv + vec2(-px.x,-px.y)).rgb;
		vec3 sx4 = dp_texture2D(Texture_First, uv + vec2( px.x, px.y)).rgb;
		vec3 sx5 = dp_texture2D(Texture_First, uv + vec2( px.x, 0.0)).rgb;
		vec3 sx6 = dp_texture2D(Texture_First, uv + vec2( px.x,-px.y)).rgb;
		vec3 sy2 = dp_texture2D(Texture_First, uv + vec2(0.0, -px.y)).rgb;
		vec3 sy5 = dp_texture2D(Texture_First, uv + vec2(0.0,  px.y)).rgb;
		vec3 luma = vec3(0.299, 0.587, 0.114);
		float gx = dot(-sx1 - 2.0*sx2 - sx3 + sx4 + 2.0*sx5 + sx6, luma);
		float gy = dot(-sx1 - 2.0*sy2 + sx3 + sx4 + 2.0*sy5 - sx6, luma);
		float edge = sqrt(gx*gx + gy*gy);
		vec3 edge_tint = mix(vec3(0.16, 0.74, 1.0), vec3(1.0, 0.32, 0.78), smoothstep(0.0, 1.0, uv.x));
		color += edge_tint * edge * edge_str;
	}

	// Atmospheric dust — particulate matter suspended in tower air
	// (was: film grain. Now: spatial dust catching light)
	float dust_density = UserVec1.w;
	float dust_seed = dot(uv * 1000.0 + fract(ClientTime * 0.05), vec2(12.9898, 78.233));
	float dust = fract(sin(dust_seed) * 43758.5453) * 2.0 - 1.0;
	vec3 dust_tint = mix(vec3(0.08, 0.86, 1.05), vec3(1.05, 0.18, 0.82), smoothstep(0.06, 0.94, uv.x));
	color += dust_tint * (dust * dust_density * 0.024) * signal_presence;

	// Signal-bound aura. This is the postprocess side of the compositor/drift
	// aggregate, but it is not allowed to draw its own screen lattice. It only
	// rides nonblack scene signal and high-contrast in-world/media edges.
	float signal_aura = UserVec2.x;
	float signal_rhythm = sin((uv.x * 9.0 + uv.y * 5.0) + ClientTime * 0.18) * 0.5 + 0.5;
	vec3 aura_tint = mix(vec3(0.02, 0.90, 1.08), vec3(1.08, 0.20, 0.80), smoothstep(0.08, 0.92, uv.x));
	color = mix(color, color * (1.0 + aura_tint * signal_rhythm * 0.32), clamp(signal_aura * signal_presence, 0.0, 0.75));
	color += vec3(0.012, 0.052, 0.072) * signal_aura * signal_presence * (0.24 + signal_rhythm * 0.36);

	// Block drift/smear: sparse image blocks, analogous to the previous
	// compositor's unstable media fragments. Kept bounded so live media remains
	// readable while the aggregate visibly differs from raw Quake output.
	vec2 block_cell = floor(uv * vec2(34.0, 19.0));
	float block_hash = fract(sin(dot(block_cell + floor(ClientTime * 0.85), vec2(127.1, 311.7))) * 43758.5453);
	float block_mask = step(0.996, block_hash) * clamp(UserVec3.y * 5.0 + UserVec2.x * 0.04, 0.0, 0.34) * signal_presence;
	vec2 block_offset = vec2((block_hash - 0.5) * 0.034, sin(block_hash * 6.28318) * 0.012);
	vec3 block_sample = dp_texture2D(Texture_First, clamp(uv + block_offset, vec2(0.0), vec2(1.0))).rgb;
	color = mix(color, max(color, block_sample * vec3(1.08, 0.78, 1.08)), block_mask);

	// Texture mode: values in 0..1 identify the active SlotDrift texture
	// family member. Values above 2 remain posterize level counts.
	float texture_mode = UserVec2.z;
	if (texture_mode > 0.05 && texture_mode <= 1.0) {
		float scanline = sin(uv.y * 1080.0 * 0.72 + ClientTime * 0.35);
		float scan_strength = 0.0;
		if (texture_mode > 0.16 && texture_mode < 0.50)
			scan_strength = 0.055;
		if (texture_mode > 0.86)
			scan_strength = max(scan_strength, 0.030);
		color *= 1.0 - max(0.0, scanline) * scan_strength * signal_presence;

		if (texture_mode > 0.28 && texture_mode < 0.40) {
			float glitch_gate = step(0.975, fract(sin(dot(block_cell + floor(ClientTime * 2.0), vec2(19.19, 71.7))) * 951.13));
			vec3 glitch_sample = dp_texture2D(Texture_First, clamp(uv + vec2(0.038, -0.010) * glitch_gate, vec2(0.0), vec2(1.0))).rgb;
			color = mix(color, max(color, glitch_sample * vec3(1.18, 0.72, 1.14)), glitch_gate * 0.38 * signal_presence);
		}

		if (texture_mode > 0.88) {
			float dither = step(0.52, fract(sin(dot(floor(uv * vec2(380.0, 214.0)), vec2(17.3, 63.1))) * 15431.7));
			color += (dither - 0.5) * vec3(0.020, 0.008, 0.026) * signal_presence;
		}

		if (texture_mode > 0.94 && texture_mode < 0.98) {
			vec2 particle_grid = vec2(70.0, 39.0);
			vec2 particle_cell = floor(uv * particle_grid);
			vec2 particle_center = (particle_cell + vec2(0.5)) / particle_grid;
			float particle_hash = fract(sin(dot(particle_cell + floor(ClientTime * 3.0), vec2(41.7, 193.1))) * 32719.37);
			float particle_gate = step(0.962, particle_hash);
			float particle_dist = length((uv - particle_center) * particle_grid);
			float particle_core = smoothstep(0.18, 0.0, particle_dist);
			vec3 particle_tint = mix(vec3(0.02, 1.05, 1.20), vec3(1.18, 0.24, 0.92), particle_hash);
			color += particle_tint * particle_core * particle_gate * (0.08 + signal_aura * 0.10) * signal_presence;
		}
	}

	// Posterize — reduce world color levels for harder material bands
	float post_levels = UserVec2.z;
	if (post_levels > 2.0) {
		color = floor(color * post_levels) / post_levels;
	}

	// Sharpen — recover ward/panel material edges after fog and bloom.
	float sharpen_str = UserVec2.w;
	if (sharpen_str > 0.001) {
		vec3 sh_l = dp_texture2D(Texture_First, uv + vec2(-px.x, 0.0)).rgb;
		vec3 sh_r = dp_texture2D(Texture_First, uv + vec2(px.x, 0.0)).rgb;
		vec3 sh_u = dp_texture2D(Texture_First, uv + vec2(0.0, px.y)).rgb;
		vec3 sh_d = dp_texture2D(Texture_First, uv + vec2(0.0, -px.y)).rgb;
		vec3 sh_blur = (sh_l + sh_r + sh_u + sh_d) * 0.25;
		color += (color - sh_blur) * sharpen_str;
	}

	// Surface granularity - abstract compositor substrate, not material grain.
	float granularity = 0.00045;
	vec2 grain_cell = floor(uv * vec2(191.0, 107.0));
	float surface_grain = fract(sin(dot(grain_cell, vec2(12.9898, 78.233))) * 43758.5453);
	vec3 grain_tint = mix(vec3(0.10, 0.75, 0.92), vec3(0.95, 0.20, 0.72), surface_grain);
	color += grain_tint * ((surface_grain - 0.5) * granularity * signal_presence);

	// Spatial warp is applied in the UV distortion phase above.

	// Animated signal noise
	float noise_str = UserVec3.y;
	if (noise_str > 0.001) {
		float n = fract(sin(dot(uv + fract(ClientTime * 0.1), vec2(12.9898, 78.233))) * 43758.5453);
		float n2 = fract(sin(dot(uv * 1.7 + fract(ClientTime * 0.07), vec2(93.989, 67.345))) * 23456.789);
		float noise_val = mix(n, n2, 0.5) * 2.0 - 1.0;
		vec3 noise_tint = mix(vec3(0.03, 0.90, 1.08), vec3(1.04, 0.18, 0.78), n2);
		color += noise_tint * (noise_val * noise_str * 0.048) * signal_presence;
	}

	// Halftone pressure, scene-signal bound.
	float ht_size = UserVec3.z;
	if (ht_size > 1.0) {
		vec2 ht_grid = vec2(ht_size * 26.0, ht_size * 14.0);
		vec2 cell = floor(uv * ht_grid);
		vec2 cell_center = (cell + vec2(0.5)) / ht_grid;
		float cell_dist = length((uv - cell_center) * ht_grid);
		float lum = dot(color, vec3(0.299, 0.587, 0.114));
		float dot_mask = step(cell_dist, max(lum, 0.20));
		vec3 dot_tint = mix(vec3(0.03, 0.25, 0.30), vec3(0.84, 0.16, 0.62), smoothstep(0.05, 0.95, uv.x));
		vec3 halftone_color = max(color, color + dot_tint * dot_mask * signal_presence * 0.105);
		color = mix(color, halftone_color, 0.62);
	}

	// Threshold / monochrome
	float thresh = UserVec3.w;
	if (thresh > 0.001) {
		float lum = dot(color, vec3(0.299, 0.587, 0.114));
		vec3 mono = vec3(smoothstep(thresh - 0.05, thresh + 0.05, lum));
		color = mix(color, mono, thresh);
	}

	// Surface emboss
	float emboss_str = UserVec4.x;
	if (emboss_str > 0.001) {
		vec3 em_tl = dp_texture2D(Texture_First, uv + vec2(-px.x, -px.y)).rgb;
		vec3 em_br = dp_texture2D(Texture_First, uv + vec2(px.x, px.y)).rgb;
		vec3 emboss = (em_br - em_tl) + vec3(0.5);
		color = mix(color, emboss * color * 2.0, emboss_str);
	}

	// Invert mix
	float inv_mix = UserVec4.y;
	if (inv_mix > 0.001) {
		color = mix(color, vec3(1.0) - color, inv_mix * signal_presence);
	}

	// Shader-load canary. Review preset 7 drives UserVec4.y above 0.95;
	// normal drift clamps stay far below this. If this never appears, the
	// runtime is not loading the Screwm override shader at all.
	if (UserVec4.y > 0.95) {
		float canary_grid = step(0.5, fract((uv.x + uv.y + ClientTime * 0.20) * 10.0));
		vec3 canary_a = vec3(0.00, 1.00, 0.32);
		vec3 canary_b = vec3(1.00, 0.00, 0.84);
		color = mix(canary_a, canary_b, canary_grid);
	}

	// Aperture pressure — a soft scroom-edge attenuation, not a hard camera
	// blackout. Earlier builds used mask_r as a literal radius and multiplied
	// most of the frame to black, which made the fixed review POV look broken.
	float mask_r = UserVec4.z;
	if (mask_r > 0.01 && mask_r < 1.0) {
		float mask_dist = distance(uv, vec2(0.5));
		float mask = smoothstep(0.35, 0.92, mask_dist);
		float mask_strength = min(mask_r, 0.25) * 0.35;
		color *= 1.0 - mask * mask_strength * signal_presence;
	}

	// Thermal field
	float thermal_mix = UserVec4.w;
	if (thermal_mix > 0.001) {
		float lum = dot(color, vec3(0.299, 0.587, 0.114));
		vec3 thermal;
		if (lum < 0.25) thermal = mix(vec3(0.0, 0.0, 0.2), vec3(0.0, 0.0, 1.0), lum * 4.0);
		else if (lum < 0.5) thermal = mix(vec3(0.0, 0.0, 1.0), vec3(0.0, 1.0, 0.0), (lum - 0.25) * 4.0);
		else if (lum < 0.75) thermal = mix(vec3(0.0, 1.0, 0.0), vec3(1.0, 1.0, 0.0), (lum - 0.5) * 4.0);
		else thermal = mix(vec3(1.0, 1.0, 0.0), vec3(1.0, 0.0, 0.0), (lum - 0.75) * 4.0);
		color = mix(color, thermal, thermal_mix * signal_presence);
	}

	// Palette cycling — subtle hue rotation over time
	float hue_shift = sin(ClientTime * 0.05) * 0.03;
	float cs = cos(hue_shift);
	float sn = sin(hue_shift);
	mat3 hue_mat = mat3(
		0.299+0.701*cs+0.168*sn, 0.587-0.587*cs+0.330*sn, 0.114-0.114*cs-0.497*sn,
		0.299-0.299*cs-0.328*sn, 0.587+0.413*cs+0.035*sn, 0.114-0.114*cs+0.292*sn,
		0.299-0.300*cs+1.250*sn, 0.587-0.588*cs-1.050*sn, 0.114+0.886*cs-0.203*sn
	);
	color = hue_mat * color;

	// Signal shear - live-state-driven chroma smear bound to existing signal.
	// No horizontal screen bands: camera review must stay stable.
	float vhs_strength = clamp(UserVec3.y * 8.0, 0.0, 1.0);
	float vhs_glitch = signal_presence * (0.0008 + signal_aura * 0.0008) * vhs_strength;
	if (vhs_glitch > 0.0001) {
		color.r = mix(color.r, dp_texture2D(Texture_First, uv + drift_dir * vhs_glitch).r, 0.55);
		color.g = mix(color.g, dp_texture2D(Texture_First, uv - drift_dir * vhs_glitch * 0.5).g, 0.35);
	}

	// Palette bias — pull the aggregate away from Quake brown and toward the
	// BitchX/ACiD/Enlightenment Scroom family without erasing live media.
	float palette_bias = 0.07;
	float lum = dot(color, vec3(0.299, 0.587, 0.114));
	vec3 scroom_tint = mix(vec3(0.72, 0.96, 1.22), vec3(1.14, 0.66, 1.16), smoothstep(0.12, 0.72, lum));
	color = mix(color, color * scroom_tint / max(dot(scroom_tint, vec3(0.333)), 0.01), palette_bias * signal_presence);

	// Luma key — shadow depth enhancement
	float lk = dot(color, vec3(0.299, 0.587, 0.114));
	color *= smoothstep(0.02, 0.08, lk) * 0.15 + 0.85;

	// Procedural noise texture — value noise, 2 octaves
	vec2 pn_uv = uv * 8.0 + vec2(ClientTime * 0.02);
	float pn1 = fract(sin(dot(floor(pn_uv), vec2(127.1, 311.7))) * 43758.5453);
	float pn2 = fract(sin(dot(floor(pn_uv * 2.0), vec2(269.5, 183.3))) * 28461.632);
	vec3 pn_tint = mix(vec3(0.05, 0.55, 0.72), vec3(0.72, 0.12, 0.55), pn2);
	color += pn_tint * ((pn1 * 0.7 + pn2 * 0.3) * 0.003 - 0.0015) * signal_presence;

	// Tile frequency modulation - only as a weak signal carrier.
	color += color * vec3(sin(uv.x * 80.0) * sin(uv.y * 60.0) * 0.004 * signal_presence);

	// Chroma key — suppress specific hue range (greens by default)
	// Useful for compositor compositing pass
	vec3 key_color = vec3(0.0, 1.0, 0.0);
	float key_dist = distance(normalize(color + vec3(0.001)), normalize(key_color));
	// (inactive by default — key_dist is always > 0 for non-green scenes)

	// Color map — limited-palette terminal surface, not Quake materialization.
	// Uses floor-based quantization across all channels
	// (complementary to posterize which uses per-channel quantization)
	float palette_res = 32.0;
	vec3 palette_color = floor(color * palette_res + 0.5) / palette_res;
	color = mix(color, palette_color, 0.06);

	// Contrast boost
	color = (color - 0.5) * 1.04 + 0.5;

	// Clamp
	color = max(color, vec3(0.0));

	// === Always-present scrim ground (no pure-black void; studio legible-but-mediated) ===
	// The scroom is seen THROUGH a translucent tinted weave: every low-signal region
	// carries the ground instead of pure black, so B2 structural-content passes by
	// construction. Warm/cool follows temperature_bias (UserVec1.z, mode-driven); the
	// tint is a bias around a neutral dark base, not a baked palette hex. Breath is
	// SPATIAL+cyclic (a slow wave across the ground), never a global pulse/flash.
	float scrim_temp = UserVec1.z;
	vec3 scrim_warm = vec3(0.165, 0.130, 0.092);
	vec3 scrim_cool = vec3(0.092, 0.120, 0.170);
	vec3 scrim_neutral = vec3(0.125, 0.125, 0.145);
	vec3 scrim_base = mix(scrim_neutral, mix(scrim_cool, scrim_warm, smoothstep(-0.5, 0.5, scrim_temp)), 0.9);
	vec2 scrim_g = uv * 6.0 + vec2(ClientTime * 0.013, ClientTime * -0.009);
	float scrim_n1 = fract(sin(dot(floor(scrim_g), vec2(127.1, 311.7))) * 43758.5453);
	float scrim_n2 = fract(sin(dot(floor(scrim_g * 2.3), vec2(269.5, 183.3))) * 28461.632);
	float scrim_gauze = scrim_n1 * 0.65 + scrim_n2 * 0.35;
	float scrim_warp = sin(uv.x * 142.0 + sin(uv.y * 12.0) * 2.0);
	float scrim_weft = sin(uv.y * 116.0 + sin(uv.x * 10.0) * 2.0);
	float scrim_weave = (scrim_warp * scrim_weft) * 0.5 + 0.5;
	float scrim_breath = 0.5 + 0.5 * sin(ClientTime * 0.31 + uv.x * 2.0 + uv.y * 1.3);
	vec2 scrim_vc = uv - 0.5;
	float scrim_invig = 1.0 + dot(scrim_vc, scrim_vc) * 0.55;
	vec3 scrim_ground = scrim_base * (0.72 + scrim_gauze * 0.42 + scrim_weave * 0.16) * scrim_invig * (0.95 + scrim_breath * 0.10);
	float scrim_final_lum = dot(color, vec3(0.299, 0.587, 0.114));
	float scrim_reveal = clamp(smoothstep(0.012, 0.10, scrim_final_lum), 0.0, 1.0);
	color = mix(scrim_ground, color, scrim_reveal);

	dp_FragColor.rgb = color;
// (removed #endif for USERVEC guard — effects now unconditional)
#endif

#ifdef USEBLOOM
	//TODO: replacing here possat back to max may be needed for HDR
	dp_FragColor += possat(dp_texture2D(Texture_Second, TexCoord1.zw) - BloomColorSubtract);
#endif

#ifdef USEVIEWTINT
	dp_FragColor = mix(dp_FragColor, ViewTintColor, ViewTintColor.a);
#endif

#ifdef USESATURATION
	//apply saturation BEFORE gamma ramps, so v_glslgamma value does not matter
	float y = dot(dp_FragColor.rgb, vec3(0.299, 0.587, 0.114));
	// 'vampire sight' effect, wheres red is compensated
	#ifdef SATURATION_REDCOMPENSATE
		float rboost = max(0.0, (dp_FragColor.r - max(dp_FragColor.g, dp_FragColor.b))*(1.0 - Saturation));
		dp_FragColor.rgb = mix(vec3(y), dp_FragColor.rgb, Saturation);
		dp_FragColor.r += rboost;
	#else
		// normal desaturation
		//dp_FragColor = vec3(y) + (dp_FragColor.rgb - vec3(y)) * Saturation;
		dp_FragColor.rgb = mix(vec3(y), dp_FragColor.rgb, Saturation);
	#endif
#endif

#ifdef USEGAMMARAMPS
	dp_FragColor.r = dp_texture2D(Texture_GammaRamps, vec2(dp_FragColor.r, 0)).r;
	dp_FragColor.g = dp_texture2D(Texture_GammaRamps, vec2(dp_FragColor.g, 0)).g;
	dp_FragColor.b = dp_texture2D(Texture_GammaRamps, vec2(dp_FragColor.b, 0)).b;
#endif
}
#endif
#else // !MODE_POSTPROCESS




#ifdef MODE_GENERIC
#ifdef USEDIFFUSE
dp_varying mediump vec2 TexCoord1;
#endif
#ifdef USESPECULAR
dp_varying mediump vec2 TexCoord2;
#endif
uniform myhalf Alpha;
#ifdef VERTEX_SHADER
void main(void)
{
#ifdef USESKELETAL
	ivec4 si0 = ivec4(Attrib_SkeletalIndex * 3.0);
	ivec4 si1 = si0 + ivec4(1, 1, 1, 1);
	ivec4 si2 = si0 + ivec4(2, 2, 2, 2);
	vec4 sw = Attrib_SkeletalWeight;
	vec4 SkeletalMatrix1 = Skeletal_Transform12[si0.x] * sw.x + Skeletal_Transform12[si0.y] * sw.y + Skeletal_Transform12[si0.z] * sw.z + Skeletal_Transform12[si0.w] * sw.w;
	vec4 SkeletalMatrix2 = Skeletal_Transform12[si1.x] * sw.x + Skeletal_Transform12[si1.y] * sw.y + Skeletal_Transform12[si1.z] * sw.z + Skeletal_Transform12[si1.w] * sw.w;
	vec4 SkeletalMatrix3 = Skeletal_Transform12[si2.x] * sw.x + Skeletal_Transform12[si2.y] * sw.y + Skeletal_Transform12[si2.z] * sw.z + Skeletal_Transform12[si2.w] * sw.w;
	mat4 SkeletalMatrix = mat4(SkeletalMatrix1, SkeletalMatrix2, SkeletalMatrix3, vec4(0.0, 0.0, 0.0, 1.0));
	vec4 SkeletalVertex = Attrib_Position * SkeletalMatrix;
#define Attrib_Position SkeletalVertex
#endif
	VertexColor = Attrib_Color;
#ifdef USEDIFFUSE
	TexCoord1 = Attrib_TexCoord0.xy;
#endif
#ifdef USESPECULAR
	TexCoord2 = Attrib_TexCoord1.xy;
#endif
	gl_Position = ModelViewProjectionMatrix * Attrib_Position;
#ifdef USETRIPPY
	gl_Position = TrippyVertex(gl_Position);
#endif
}
#endif

#ifdef FRAGMENT_SHADER
#ifdef USEDIFFUSE
uniform sampler2D Texture_First;
#endif
#ifdef USESPECULAR
uniform sampler2D Texture_Second;
#endif
#ifdef USEGAMMARAMPS
uniform sampler2D Texture_GammaRamps;
#endif

void main(void)
{
#ifdef USEVIEWTINT
	dp_FragColor = VertexColor;
#else
	dp_FragColor = vec4(1.0, 1.0, 1.0, 1.0);
#endif
#ifdef USEDIFFUSE
# ifdef USEREFLECTCUBE
	// suppress texture alpha
	dp_FragColor.rgb *= dp_texture2D(Texture_First, TexCoord1).rgb;
# else
	dp_FragColor *= dp_texture2D(Texture_First, TexCoord1);
# endif
#endif

#ifdef USESPECULAR
	vec4 tex2 = dp_texture2D(Texture_Second, TexCoord2);
# ifdef USECOLORMAPPING
	dp_FragColor *= tex2;
# endif
# ifdef USEGLOW
	dp_FragColor += tex2;
# endif
# ifdef USEVERTEXTEXTUREBLEND
	dp_FragColor = mix(dp_FragColor, tex2, tex2.a);
# endif
#endif
#ifdef USEGAMMARAMPS
	dp_FragColor.r = dp_texture2D(Texture_GammaRamps, vec2(dp_FragColor.r, 0)).r;
	dp_FragColor.g = dp_texture2D(Texture_GammaRamps, vec2(dp_FragColor.g, 0)).g;
	dp_FragColor.b = dp_texture2D(Texture_GammaRamps, vec2(dp_FragColor.b, 0)).b;
#endif
#ifdef USEALPHAKILL
	dp_FragColor.a *= Alpha;
#endif
}
#endif
#else // !MODE_GENERIC




#ifdef MODE_BLOOMBLUR
dp_varying mediump vec2 TexCoord;
#ifdef VERTEX_SHADER
void main(void)
{
	VertexColor = Attrib_Color;
	TexCoord = Attrib_TexCoord0.xy;
	gl_Position = ModelViewProjectionMatrix * Attrib_Position;
}
#endif

#ifdef FRAGMENT_SHADER
uniform sampler2D Texture_First;
uniform mediump vec4 BloomBlur_Parameters;

void main(void)
{
	int i;
	vec2 tc = TexCoord;
	vec3 color = dp_texture2D(Texture_First, tc).rgb;
	tc += BloomBlur_Parameters.xy;
	for (i = 1;i < SAMPLES;i++)
	{
		color += dp_texture2D(Texture_First, tc).rgb;
		tc += BloomBlur_Parameters.xy;
	}
	dp_FragColor = vec4(color * BloomBlur_Parameters.z + vec3(BloomBlur_Parameters.w), 1);
}
#endif
#else // !MODE_BLOOMBLUR
#ifdef MODE_REFRACTION
dp_varying mediump vec2 TexCoord;
dp_varying highp vec4 ModelViewProjectionPosition;
uniform highp mat4 TexMatrix;
#ifdef VERTEX_SHADER

void main(void)
{
#ifdef USESKELETAL
	ivec4 si0 = ivec4(Attrib_SkeletalIndex * 3.0);
	ivec4 si1 = si0 + ivec4(1, 1, 1, 1);
	ivec4 si2 = si0 + ivec4(2, 2, 2, 2);
	vec4 sw = Attrib_SkeletalWeight;
	vec4 SkeletalMatrix1 = Skeletal_Transform12[si0.x] * sw.x + Skeletal_Transform12[si0.y] * sw.y + Skeletal_Transform12[si0.z] * sw.z + Skeletal_Transform12[si0.w] * sw.w;
	vec4 SkeletalMatrix2 = Skeletal_Transform12[si1.x] * sw.x + Skeletal_Transform12[si1.y] * sw.y + Skeletal_Transform12[si1.z] * sw.z + Skeletal_Transform12[si1.w] * sw.w;
	vec4 SkeletalMatrix3 = Skeletal_Transform12[si2.x] * sw.x + Skeletal_Transform12[si2.y] * sw.y + Skeletal_Transform12[si2.z] * sw.z + Skeletal_Transform12[si2.w] * sw.w;
	mat4 SkeletalMatrix = mat4(SkeletalMatrix1, SkeletalMatrix2, SkeletalMatrix3, vec4(0.0, 0.0, 0.0, 1.0));
	vec4 SkeletalVertex = Attrib_Position * SkeletalMatrix;
#define Attrib_Position SkeletalVertex
#endif
#ifdef USEALPHAGENVERTEX
	VertexColor = Attrib_Color;
#endif
	TexCoord = vec2(TexMatrix * Attrib_TexCoord0);
	gl_Position = ModelViewProjectionMatrix * Attrib_Position;
	ModelViewProjectionPosition = gl_Position;
#ifdef USETRIPPY
	gl_Position = TrippyVertex(gl_Position);
#endif
}
#endif

#ifdef FRAGMENT_SHADER
uniform sampler2D Texture_Normal;
uniform sampler2D Texture_Refraction;

uniform mediump vec4 DistortScaleRefractReflect;
uniform mediump vec4 ScreenScaleRefractReflect;
uniform mediump vec4 ScreenCenterRefractReflect;
uniform mediump vec4 RefractColor;
uniform mediump vec4 ReflectColor;
uniform highp float ClientTime;
#ifdef USENORMALMAPSCROLLBLEND
uniform highp vec2 NormalmapScrollBlend;
#endif

void main(void)
{
	vec2 ScreenScaleRefractReflectIW = ScreenScaleRefractReflect.xy * (1.0 / ModelViewProjectionPosition.w);
	//vec2 ScreenTexCoord = (ModelViewProjectionPosition.xy + normalize(vec3(dp_texture2D(Texture_Normal, TexCoord)) - vec3(0.5)).xy * DistortScaleRefractReflect.xy * 100) * ScreenScaleRefractReflectIW + ScreenCenterRefractReflect.xy;
	vec2 SafeScreenTexCoord = ModelViewProjectionPosition.xy * ScreenScaleRefractReflectIW + ScreenCenterRefractReflect.xy;
#ifdef USEALPHAGENVERTEX
	vec2 distort = DistortScaleRefractReflect.xy * VertexColor.a;
	vec4 refractcolor = mix(RefractColor, vec4(1.0, 1.0, 1.0, 1.0), VertexColor.a);
#else
	vec2 distort = DistortScaleRefractReflect.xy;
	vec4 refractcolor = RefractColor;
#endif
	#ifdef USENORMALMAPSCROLLBLEND
		vec3 normal = dp_texture2D(Texture_Normal, (TexCoord + vec2(0.08, 0.08)*ClientTime*NormalmapScrollBlend.x*0.5)*NormalmapScrollBlend.y).rgb - vec3(1.0);
		normal += dp_texture2D(Texture_Normal, (TexCoord + vec2(-0.06, -0.09)*ClientTime*NormalmapScrollBlend.x)*NormalmapScrollBlend.y*0.75).rgb;
		vec2 ScreenTexCoord = SafeScreenTexCoord + vec3(normalize(cast_myhalf3(normal))).xy * distort;
	#else
		vec2 ScreenTexCoord = SafeScreenTexCoord + vec3(normalize(cast_myhalf3(dp_texture2D(Texture_Normal, TexCoord)) - cast_myhalf3(0.5))).xy * distort;
	#endif
	// FIXME temporary hack to detect the case that the reflection
	// gets blackened at edges due to leaving the area that contains actual
	// content.
	// Remove this 'ack once we have a better way to stop this thing from
	// 'appening.
	float f = minonesat(length(dp_texture2D(Texture_Refraction, ScreenTexCoord + vec2(0.01, 0.01)).rgb) / 0.05);
	f      *= minonesat(length(dp_texture2D(Texture_Refraction, ScreenTexCoord + vec2(0.01, -0.01)).rgb) / 0.05);
	f      *= minonesat(length(dp_texture2D(Texture_Refraction, ScreenTexCoord + vec2(-0.01, 0.01)).rgb) / 0.05);
	f      *= minonesat(length(dp_texture2D(Texture_Refraction, ScreenTexCoord + vec2(-0.01, -0.01)).rgb) / 0.05);
	ScreenTexCoord = mix(SafeScreenTexCoord, ScreenTexCoord, f);
	dp_FragColor = vec4(dp_texture2D(Texture_Refraction, ScreenTexCoord).rgb, 1.0) * refractcolor;
}
#endif
#else // !MODE_REFRACTION




#ifdef MODE_WATER
dp_varying mediump vec2 TexCoord;
dp_varying highp vec3 EyeVector;
dp_varying highp vec4 ModelViewProjectionPosition;
#ifdef VERTEX_SHADER
uniform highp vec3 EyePosition;
uniform highp mat4 TexMatrix;

void main(void)
{
#ifdef USESKELETAL
	ivec4 si0 = ivec4(Attrib_SkeletalIndex * 3.0);
	ivec4 si1 = si0 + ivec4(1, 1, 1, 1);
	ivec4 si2 = si0 + ivec4(2, 2, 2, 2);
	vec4 sw = Attrib_SkeletalWeight;
	vec4 SkeletalMatrix1 = Skeletal_Transform12[si0.x] * sw.x + Skeletal_Transform12[si0.y] * sw.y + Skeletal_Transform12[si0.z] * sw.z + Skeletal_Transform12[si0.w] * sw.w;
	vec4 SkeletalMatrix2 = Skeletal_Transform12[si1.x] * sw.x + Skeletal_Transform12[si1.y] * sw.y + Skeletal_Transform12[si1.z] * sw.z + Skeletal_Transform12[si1.w] * sw.w;
	vec4 SkeletalMatrix3 = Skeletal_Transform12[si2.x] * sw.x + Skeletal_Transform12[si2.y] * sw.y + Skeletal_Transform12[si2.z] * sw.z + Skeletal_Transform12[si2.w] * sw.w;
	mat4 SkeletalMatrix = mat4(SkeletalMatrix1, SkeletalMatrix2, SkeletalMatrix3, vec4(0.0, 0.0, 0.0, 1.0));
	mat3 SkeletalNormalMatrix = mat3(cross(SkeletalMatrix[1].xyz, SkeletalMatrix[2].xyz), cross(SkeletalMatrix[2].xyz, SkeletalMatrix[0].xyz), cross(SkeletalMatrix[0].xyz, SkeletalMatrix[1].xyz)); // is actually transpose(inverse(mat3(SkeletalMatrix))) * det(mat3(SkeletalMatrix))
	vec4 SkeletalVertex = Attrib_Position * SkeletalMatrix;
	vec3 SkeletalSVector = normalize(Attrib_TexCoord1.xyz * SkeletalNormalMatrix);
	vec3 SkeletalTVector = normalize(Attrib_TexCoord2.xyz * SkeletalNormalMatrix);
	vec3 SkeletalNormal  = normalize(Attrib_TexCoord3.xyz * SkeletalNormalMatrix);
#define Attrib_Position SkeletalVertex
#define Attrib_TexCoord1 SkeletalSVector
#define Attrib_TexCoord2 SkeletalTVector
#define Attrib_TexCoord3 SkeletalNormal
#endif
#ifdef USEALPHAGENVERTEX
	VertexColor = Attrib_Color;
#endif
	TexCoord = vec2(TexMatrix * Attrib_TexCoord0);
	vec3 EyeRelative = EyePosition - Attrib_Position.xyz;
	EyeVector.x = dot(EyeRelative, Attrib_TexCoord1.xyz);
	EyeVector.y = dot(EyeRelative, Attrib_TexCoord2.xyz);
	EyeVector.z = dot(EyeRelative, Attrib_TexCoord3.xyz);
	gl_Position = ModelViewProjectionMatrix * Attrib_Position;
	ModelViewProjectionPosition = gl_Position;
#ifdef USETRIPPY
	gl_Position = TrippyVertex(gl_Position);
#endif
}
#endif

#ifdef FRAGMENT_SHADER
uniform sampler2D Texture_Normal;
uniform sampler2D Texture_Refraction;
uniform sampler2D Texture_Reflection;

uniform mediump vec4 DistortScaleRefractReflect;
uniform mediump vec4 ScreenScaleRefractReflect;
uniform mediump vec4 ScreenCenterRefractReflect;
uniform mediump vec4 RefractColor;
uniform mediump vec4 ReflectColor;
uniform mediump float ReflectFactor;
uniform mediump float ReflectOffset;
uniform highp float ClientTime;
#ifdef USENORMALMAPSCROLLBLEND
uniform highp vec2 NormalmapScrollBlend;
#endif

void main(void)
{
	vec4 ScreenScaleRefractReflectIW = ScreenScaleRefractReflect * (1.0 / ModelViewProjectionPosition.w);
	//vec4 ScreenTexCoord = (ModelViewProjectionPosition.xyxy + normalize(vec3(dp_texture2D(Texture_Normal, TexCoord)) - vec3(0.5)).xyxy * DistortScaleRefractReflect * 100) * ScreenScaleRefractReflectIW + ScreenCenterRefractReflect;
	vec4 SafeScreenTexCoord = ModelViewProjectionPosition.xyxy * ScreenScaleRefractReflectIW + ScreenCenterRefractReflect;
	//SafeScreenTexCoord = gl_FragCoord.xyxy * vec4(1.0 / 1920.0, 1.0 / 1200.0, 1.0 / 1920.0, 1.0 / 1200.0);
	// slight water animation via 2 layer scrolling (todo: tweak)
#ifdef USEALPHAGENVERTEX
	vec4 distort = DistortScaleRefractReflect * VertexColor.a;
	float reflectoffset = ReflectOffset * VertexColor.a;
	float reflectfactor = ReflectFactor * VertexColor.a;
	vec4 refractcolor = mix(RefractColor, vec4(1.0, 1.0, 1.0, 1.0), VertexColor.a);
#else
	vec4 distort = DistortScaleRefractReflect;
	float reflectoffset = ReflectOffset;
	float reflectfactor = ReflectFactor;
	vec4 refractcolor = RefractColor;
#endif
	#ifdef USENORMALMAPSCROLLBLEND
		vec3 normal = dp_texture2D(Texture_Normal, (TexCoord + vec2(0.08, 0.08)*ClientTime*NormalmapScrollBlend.x*0.5)*NormalmapScrollBlend.y).rgb - vec3(1.0);
		normal += dp_texture2D(Texture_Normal, (TexCoord + vec2(-0.06, -0.09)*ClientTime*NormalmapScrollBlend.x)*NormalmapScrollBlend.y*0.75).rgb;
		vec4 ScreenTexCoord = SafeScreenTexCoord + (normalize(normal) + vec3(0.15)).xyxy * distort;
	#else
		vec4 ScreenTexCoord = SafeScreenTexCoord + vec2(normalize(vec3(dp_texture2D(Texture_Normal, TexCoord)) - vec3(0.5))).xyxy * distort;
	#endif
	// FIXME temporary hack to detect the case that the reflection
	// gets blackened at edges due to leaving the area that contains actual
	// content.
	// Remove this 'ack once we have a better way to stop this thing from
	// 'appening.
	float f  = minonesat(length(dp_texture2D(Texture_Refraction, ScreenTexCoord.xy + vec2(0.005, 0.01)).rgb) / 0.002);
	f       *= minonesat(length(dp_texture2D(Texture_Refraction, ScreenTexCoord.xy + vec2(0.005, -0.01)).rgb) / 0.002);
	f       *= minonesat(length(dp_texture2D(Texture_Refraction, ScreenTexCoord.xy + vec2(-0.005, 0.01)).rgb) / 0.002);
	f       *= minonesat(length(dp_texture2D(Texture_Refraction, ScreenTexCoord.xy + vec2(-0.005, -0.01)).rgb) / 0.002);
	ScreenTexCoord.xy = mix(SafeScreenTexCoord.xy, ScreenTexCoord.xy, f);
	f  = minonesat(length(dp_texture2D(Texture_Reflection, ScreenTexCoord.zw + vec2(0.005, 0.005)).rgb) / 0.002);
	f *= minonesat(length(dp_texture2D(Texture_Reflection, ScreenTexCoord.zw + vec2(0.005, -0.005)).rgb) / 0.002);
	f *= minonesat(length(dp_texture2D(Texture_Reflection, ScreenTexCoord.zw + vec2(-0.005, 0.005)).rgb) / 0.002);
	f *= minonesat(length(dp_texture2D(Texture_Reflection, ScreenTexCoord.zw + vec2(-0.005, -0.005)).rgb) / 0.002);
	ScreenTexCoord.zw = mix(SafeScreenTexCoord.zw, ScreenTexCoord.zw, f);
	float Fresnel = pow(min(1.0, 1.0 - float(normalize(EyeVector).z)), 2.0) * reflectfactor + reflectoffset;
	dp_FragColor = mix(vec4(dp_texture2D(Texture_Refraction, ScreenTexCoord.xy).rgb, 1) * refractcolor, vec4(dp_texture2D(Texture_Reflection, ScreenTexCoord.zw).rgb, 1) * ReflectColor, Fresnel);
}
#endif
#else // !MODE_WATER




// common definitions between vertex shader and fragment shader:

dp_varying mediump vec4 TexCoordSurfaceLightmap;
#ifdef USEVERTEXTEXTUREBLEND
dp_varying mediump vec2 TexCoord2;
#endif

#ifdef MODE_LIGHTSOURCE
dp_varying mediump vec3 CubeVector;
#endif

#if (defined(MODE_LIGHTSOURCE) || defined(MODE_LIGHTDIRECTION)) && defined(USEDIFFUSE)
dp_varying mediump vec3 LightVector;
#endif

#ifdef USEEYEVECTOR
dp_varying highp vec4 EyeVectorFogDepth;
#endif

#if defined(MODE_LIGHTDIRECTIONMAP_MODELSPACE) || defined(MODE_DEFERREDGEOMETRY) || defined(USEREFLECTCUBE) || defined(USEBOUNCEGRIDDIRECTIONAL) || defined(MODE_LIGHTGRID)
dp_varying highp vec4 VectorS; // direction of S texcoord (sometimes crudely called tangent)
dp_varying highp vec4 VectorT; // direction of T texcoord (sometimes crudely called binormal)
dp_varying highp vec4 VectorR; // direction of R texcoord (surface normal)
#else
# ifdef USEFOG
dp_varying highp vec3 EyeVectorModelSpace;
# endif
#endif

#ifdef USEREFLECTION
dp_varying highp vec4 ModelViewProjectionPosition;
#endif
#ifdef MODE_DEFERREDLIGHTSOURCE
uniform highp vec3 LightPosition;
dp_varying highp vec4 ModelViewPosition;
#endif

#ifdef MODE_LIGHTSOURCE
uniform highp vec3 LightPosition;
#endif
uniform highp vec3 EyePosition;
#ifdef MODE_LIGHTDIRECTION
uniform highp vec3 LightDir;
#endif
uniform highp vec4 FogPlane;

#ifdef USESHADOWMAPORTHO
dp_varying highp vec3 ShadowMapTC;
#endif

#ifdef MODE_LIGHTGRID
dp_varying highp vec3 LightGridTC;
#endif
#ifdef USEBOUNCEGRID
dp_varying highp vec3 BounceGridTexCoord;
#endif

#ifdef MODE_DEFERREDGEOMETRY
dp_varying highp float Depth;
#endif






// TODO: get rid of tangentt (texcoord2) and use a crossproduct to regenerate it from tangents (texcoord1) and normal (texcoord3), this would require sending a 4 component texcoord1 with W as 1 or -1 according to which side the texcoord2 should be on

// fragment shader specific:
#ifdef FRAGMENT_SHADER

uniform sampler2D Texture_Normal;
uniform sampler2D Texture_Color;
uniform sampler2D Texture_Gloss;
#ifdef USEGLOW
uniform sampler2D Texture_Glow;
#endif
#ifdef USEVERTEXTEXTUREBLEND
uniform sampler2D Texture_SecondaryNormal;
uniform sampler2D Texture_SecondaryColor;
uniform sampler2D Texture_SecondaryGloss;
#ifdef USEGLOW
uniform sampler2D Texture_SecondaryGlow;
#endif
#endif
#ifdef USECOLORMAPPING
uniform sampler2D Texture_Pants;
uniform sampler2D Texture_Shirt;
#endif
#ifdef USEFOG
#ifdef USEFOGHEIGHTTEXTURE
uniform sampler2D Texture_FogHeightTexture;
#endif
uniform sampler2D Texture_FogMask;
#endif
#ifdef USELIGHTMAP
uniform sampler2D Texture_Lightmap;
#endif
#if defined(MODE_LIGHTDIRECTIONMAP_MODELSPACE) || defined(MODE_LIGHTDIRECTIONMAP_TANGENTSPACE)
uniform sampler2D Texture_Deluxemap;
#endif
#ifdef USEREFLECTION
uniform sampler2D Texture_Reflection;
#endif

#ifdef MODE_DEFERREDLIGHTSOURCE
uniform sampler2D Texture_ScreenNormalMap;
#endif
#ifdef USEDEFERREDLIGHTMAP
#ifdef USECELOUTLINES
uniform sampler2D Texture_ScreenNormalMap;
#endif
uniform sampler2D Texture_ScreenDiffuse;
uniform sampler2D Texture_ScreenSpecular;
#endif

uniform mediump vec3 Color_Pants;
uniform mediump vec3 Color_Shirt;
uniform mediump vec3 FogColor;

#ifdef USEFOG
uniform highp float FogRangeRecip;
uniform highp float FogPlaneViewDist;
uniform highp float FogHeightFade;
vec3 FogVertex(vec4 surfacecolor)
{
#if defined(MODE_LIGHTDIRECTIONMAP_MODELSPACE) || defined(MODE_DEFERREDGEOMETRY) || defined(USEREFLECTCUBE) || defined(USEBOUNCEGRIDDIRECTIONAL) || defined(MODE_LIGHTGRID)
	vec3 EyeVectorModelSpace = vec3(VectorS.w, VectorT.w, VectorR.w);
#endif
	float FogPlaneVertexDist = EyeVectorFogDepth.w;
	float fogfrac;
       vec3 fc = FogColor;
#ifdef USEFOGALPHAHACK
	fc *= surfacecolor.a;
#endif
#ifdef USEFOGHEIGHTTEXTURE
	vec4 fogheightpixel = dp_texture2D(Texture_FogHeightTexture, vec2(1,1) + vec2(FogPlaneVertexDist, FogPlaneViewDist) * (-2.0 * FogHeightFade));
	fogfrac = fogheightpixel.a;
	return mix(fogheightpixel.rgb * fc, surfacecolor.rgb, dp_texture2D(Texture_FogMask, cast_myhalf2(length(EyeVectorModelSpace)*fogfrac*FogRangeRecip, 0.0)).r);
#else
# ifdef USEFOGOUTSIDE
	fogfrac = min(0.0, FogPlaneVertexDist) / (FogPlaneVertexDist - FogPlaneViewDist) * min(1.0, min(0.0, FogPlaneVertexDist) * FogHeightFade);
# else
	fogfrac = FogPlaneViewDist / (FogPlaneViewDist - max(0.0, FogPlaneVertexDist)) * min(1.0, (min(0.0, FogPlaneVertexDist) + FogPlaneViewDist) * FogHeightFade);
# endif
	return mix(fc, surfacecolor.rgb, dp_texture2D(Texture_FogMask, cast_myhalf2(length(EyeVectorModelSpace)*fogfrac*FogRangeRecip, 0.0)).r);
#endif
}
#endif

#ifdef USEOFFSETMAPPING
uniform mediump vec4 OffsetMapping_ScaleSteps;
uniform mediump float OffsetMapping_Bias;
#ifdef USEOFFSETMAPPING_LOD
uniform mediump float OffsetMapping_LodDistance;
#endif
vec2 OffsetMapping(vec2 TexCoord, vec2 dPdx, vec2 dPdy)
{
	float i;
	// distance-based LOD
#ifdef USEOFFSETMAPPING_LOD
	//mediump float LODFactor = min(1.0, OffsetMapping_LodDistance / EyeVectorFogDepth.z);
	//mediump vec4 ScaleSteps = vec4(OffsetMapping_ScaleSteps.x, OffsetMapping_ScaleSteps.y * LODFactor, OffsetMapping_ScaleSteps.z / LODFactor, OffsetMapping_ScaleSteps.w * LODFactor);
	mediump float GuessLODFactor = min(1.0, OffsetMapping_LodDistance / EyeVectorFogDepth.z);
#ifdef USEOFFSETMAPPING_RELIEFMAPPING
	// stupid workaround because 1-step and 2-step reliefmapping is void
	mediump float LODSteps = max(3.0, ceil(GuessLODFactor * OffsetMapping_ScaleSteps.y));
#else
	mediump float LODSteps = ceil(GuessLODFactor * OffsetMapping_ScaleSteps.y);
#endif
	mediump vec4 ScaleSteps = vec4(OffsetMapping_ScaleSteps.x, LODSteps, vec2(1.0, OffsetMapping_ScaleSteps.w * LODSteps) / vec2(LODSteps, OffsetMapping_ScaleSteps.y));
#else
	#define ScaleSteps OffsetMapping_ScaleSteps
#endif
#ifdef USEOFFSETMAPPING_RELIEFMAPPING
	float f;
	// 14 sample relief mapping: linear search and then binary search
	// this basically steps forward a small amount repeatedly until it finds
	// itself inside solid, then jitters forward and back using decreasing
	// amounts to find the impact
	//vec3 OffsetVector = vec3(EyeVectorFogDepth.xy * ((1.0 / EyeVectorFogDepth.z) * ScaleSteps.x) * vec2(-1, 1), -1);
	//vec3 OffsetVector = vec3(normalize(EyeVectorFogDepth.xy) * ScaleSteps.x * vec2(-1, 1), -1);
	vec3 OffsetVector = vec3(normalize(EyeVectorFogDepth.xyz).xy * ScaleSteps.x * vec2(-1, 1), -1);
	vec3 RT = vec3(vec2(TexCoord.xy - OffsetVector.xy*OffsetMapping_Bias), 1);
	OffsetVector *= ScaleSteps.z;
	for(i = 1.0; i < ScaleSteps.y; ++i)
		RT += OffsetVector *  step(dp_textureGrad(Texture_Normal, RT.xy, dPdx, dPdy).a, RT.z);
	for(i = 0.0, f = 1.0; i < ScaleSteps.w; ++i, f *= 0.5)
		RT += OffsetVector * (step(dp_textureGrad(Texture_Normal, RT.xy, dPdx, dPdy).a, RT.z) * f - 0.5 * f);
	return RT.xy;
#else
	// 2 sample offset mapping (only 2 samples because of ATI Radeon 9500-9800/X300 limits)
	//vec2 OffsetVector = vec2(EyeVectorFogDepth.xy * ((1.0 / EyeVectorFogDepth.z) * ScaleSteps.x) * vec2(-1, 1));
	//vec2 OffsetVector = vec2(normalize(EyeVectorFogDepth.xy) * ScaleSteps.x * vec2(-1, 1));
	vec2 OffsetVector = vec2(normalize(EyeVectorFogDepth.xyz).xy * ScaleSteps.x * vec2(-1, 1));
	OffsetVector *= ScaleSteps.z;
	vec2 OneMinusBias_OffsetVector = (1.0 - OffsetMapping_Bias) * OffsetVector;
	for(i = 0.0; i < ScaleSteps.y; ++i)
		TexCoord += -dp_textureGrad(Texture_Normal, TexCoord, dPdx, dPdy).a * OffsetVector + OneMinusBias_OffsetVector;
	return TexCoord;
#endif
}
#endif // USEOFFSETMAPPING

#if defined(MODE_LIGHTSOURCE) || defined(MODE_DEFERREDLIGHTSOURCE)
uniform sampler2D Texture_Attenuation;
uniform samplerCube Texture_Cube;
#endif

#if defined(MODE_LIGHTSOURCE) || defined(MODE_DEFERREDLIGHTSOURCE) || defined(USESHADOWMAPORTHO)

#ifdef USESHADOWMAP2D
# ifdef USESHADOWSAMPLER
uniform sampler2DShadow Texture_ShadowMap2D;
# else
uniform sampler2D Texture_ShadowMap2D;
# endif
#endif

#ifdef USESHADOWMAPVSDCT
uniform samplerCube Texture_CubeProjection;
#endif

#if defined(USESHADOWMAP2D)
uniform mediump vec4 ShadowMap_TextureScale;
uniform mediump vec4 ShadowMap_Parameters;
#endif

#if defined(USESHADOWMAP2D)
# ifdef USESHADOWMAPORTHO
#  define GetShadowMapTC2D(dir) (max(vec3(0.0, 0.0, 0.0), min(dir, ShadowMap_Parameters.xyz)))
# else
#  ifdef USESHADOWMAPVSDCT
vec3 GetShadowMapTC2D(vec3 dir)
{
	vec3 adir = abs(dir);
	float m = max(max(adir.x, adir.y), adir.z);
	vec4 proj = dp_textureCube(Texture_CubeProjection, dir);
#ifdef USEDEPTHRGB
	return vec3(mix(dir.xy, dir.zz, proj.xy) * (ShadowMap_Parameters.x / m) +  proj.zw * ShadowMap_Parameters.z, m + 64.0 * ShadowMap_Parameters.w);
#else
	vec2 mparams = ShadowMap_Parameters.xy / m;
	return vec3(mix(dir.xy, dir.zz, proj.xy) * mparams.x + proj.zw * ShadowMap_Parameters.z, mparams.y + ShadowMap_Parameters.w);
#endif
}
#  else
vec3 GetShadowMapTC2D(vec3 dir)
{
	vec3 adir = abs(dir);
	float m; vec4 proj;
	if (adir.x > adir.y) { m = adir.x; proj = vec4(dir.zyx, 0.5); } else { m = adir.y; proj = vec4(dir.xzy, 1.5); }
	if (adir.z > m) { m = adir.z; proj = vec4(dir, 2.5); }
#ifdef USEDEPTHRGB
	return vec3(proj.xy * (ShadowMap_Parameters.x / m) + vec2(0.5,0.5) + vec2(proj.z < 0.0 ? 1.5 : 0.5, proj.w) * ShadowMap_Parameters.z, m + 64.0 * ShadowMap_Parameters.w);
#else
	vec2 mparams = ShadowMap_Parameters.xy / m;
	return vec3(proj.xy * mparams.x + vec2(proj.z < 0.0 ? 1.5 : 0.5, proj.w) * ShadowMap_Parameters.z, mparams.y + ShadowMap_Parameters.w);
#endif
}
#  endif
# endif
#endif // defined(USESHADOWMAP2D)

# ifdef USESHADOWMAP2D
float ShadowMapCompare(vec3 dir)
{
	vec3 shadowmaptc = GetShadowMapTC2D(dir) + vec3(ShadowMap_TextureScale.zw, 0.0f);
	float f;

#  ifdef USEDEPTHRGB
#   ifdef USESHADOWMAPPCF
#    define texval(x, y) decodedepthmacro(dp_texture2D(Texture_ShadowMap2D, center + vec2(x, y)*ShadowMap_TextureScale.xy))
#    if USESHADOWMAPPCF > 1
	vec2 center = shadowmaptc.xy - 0.5, offset = fract(center);
	center *= ShadowMap_TextureScale.xy;
	vec4 row1 = step(shadowmaptc.z, vec4(texval(-1.0, -1.0), texval( 0.0, -1.0), texval( 1.0, -1.0), texval( 2.0, -1.0)));
	vec4 row2 = step(shadowmaptc.z, vec4(texval(-1.0,  0.0), texval( 0.0,  0.0), texval( 1.0,  0.0), texval( 2.0,  0.0)));
	vec4 row3 = step(shadowmaptc.z, vec4(texval(-1.0,  1.0), texval( 0.0,  1.0), texval( 1.0,  1.0), texval( 2.0,  1.0)));
	vec4 row4 = step(shadowmaptc.z, vec4(texval(-1.0,  2.0), texval( 0.0,  2.0), texval( 1.0,  2.0), texval( 2.0,  2.0)));
	vec4 cols = row2 + row3 + mix(row1, row4, offset.y);
	f = dot(mix(cols.xyz, cols.yzw, offset.x), vec3(1.0/9.0));
#    else
	vec2 center = shadowmaptc.xy*ShadowMap_TextureScale.xy, offset = fract(shadowmaptc.xy);
	vec3 row1 = step(shadowmaptc.z, vec3(texval(-1.0, -1.0), texval( 0.0, -1.0), texval( 1.0, -1.0)));
	vec3 row2 = step(shadowmaptc.z, vec3(texval(-1.0,  0.0), texval( 0.0,  0.0), texval( 1.0,  0.0)));
	vec3 row3 = step(shadowmaptc.z, vec3(texval(-1.0,  1.0), texval( 0.0,  1.0), texval( 1.0,  1.0)));
	vec3 cols = row2 + mix(row1, row3, offset.y);
	f = dot(mix(cols.xy, cols.yz, offset.x), vec2(0.25));
#    endif
#   else
	f = step(shadowmaptc.z, decodedepthmacro(dp_texture2D(Texture_ShadowMap2D, shadowmaptc.xy*ShadowMap_TextureScale.xy)));
#   endif
#  else
#   ifdef USESHADOWSAMPLER
#     ifdef USESHADOWMAPPCF
#       define texval(off) dp_shadow2D(Texture_ShadowMap2D, vec3(off, shadowmaptc.z))  
	vec2 offset = fract(shadowmaptc.xy - 0.5);
   vec4 size = vec4(offset + 1.0, 2.0 - offset);
#       if USESHADOWMAPPCF > 1
   vec2 center = (shadowmaptc.xy - offset + 0.5)*ShadowMap_TextureScale.xy;
   vec4 weight = (vec4(-1.5, -1.5, 2.0, 2.0) + (shadowmaptc.xy - 0.5*offset).xyxy)*ShadowMap_TextureScale.xyxy;
	f = (1.0/25.0)*dot(size.zxzx*size.wwyy, vec4(texval(weight.xy), texval(weight.zy), texval(weight.xw), texval(weight.zw))) +
		(2.0/25.0)*dot(size, vec4(texval(vec2(weight.z, center.y)), texval(vec2(center.x, weight.w)), texval(vec2(weight.x, center.y)), texval(vec2(center.x, weight.y)))) +
		(4.0/25.0)*texval(center);
#       else
	vec4 weight = (vec4(1.0, 1.0, -0.5, -0.5) + (shadowmaptc.xy - 0.5*offset).xyxy)*ShadowMap_TextureScale.xyxy;
	f = (1.0/9.0)*dot(size.zxzx*size.wwyy, vec4(texval(weight.zw), texval(weight.xw), texval(weight.zy), texval(weight.xy)));
#       endif        
#     else
	f = dp_shadow2D(Texture_ShadowMap2D, vec3(shadowmaptc.xy*ShadowMap_TextureScale.xy, shadowmaptc.z));
#     endif
#   else
#     ifdef USESHADOWMAPPCF
#      if defined(GL_ARB_texture_gather) || defined(GL_AMD_texture_texture4)
#       ifdef GL_ARB_texture_gather
#         define texval(x, y) textureGatherOffset(Texture_ShadowMap2D, center, ivec2(x, y))
#       else
#         define texval(x, y) texture4(Texture_ShadowMap2D, center + vec2(x, y)*ShadowMap_TextureScale.xy)
#       endif
	vec2 offset = fract(shadowmaptc.xy - 0.5), center = (shadowmaptc.xy - offset)*ShadowMap_TextureScale.xy;
#       if USESHADOWMAPPCF > 1
   vec4 group1 = step(shadowmaptc.z, texval(-2.0, -2.0));
   vec4 group2 = step(shadowmaptc.z, texval( 0.0, -2.0));
   vec4 group3 = step(shadowmaptc.z, texval( 2.0, -2.0));
   vec4 group4 = step(shadowmaptc.z, texval(-2.0,  0.0));
   vec4 group5 = step(shadowmaptc.z, texval( 0.0,  0.0));
   vec4 group6 = step(shadowmaptc.z, texval( 2.0,  0.0));
   vec4 group7 = step(shadowmaptc.z, texval(-2.0,  2.0));
   vec4 group8 = step(shadowmaptc.z, texval( 0.0,  2.0));
   vec4 group9 = step(shadowmaptc.z, texval( 2.0,  2.0));
	vec4 locols = vec4(group1.ab, group3.ab);
	vec4 hicols = vec4(group7.rg, group9.rg);
	locols.yz += group2.ab;
	hicols.yz += group8.rg;
	vec4 midcols = vec4(group1.rg, group3.rg) + vec4(group7.ab, group9.ab) +
				vec4(group4.rg, group6.rg) + vec4(group4.ab, group6.ab) +
				mix(locols, hicols, offset.y);
	vec4 cols = group5 + vec4(group2.rg, group8.ab);
	cols.xyz += mix(midcols.xyz, midcols.yzw, offset.x);
	f = dot(cols, vec4(1.0/25.0));
#      else
	vec4 group1 = step(shadowmaptc.z, texval(-1.0, -1.0));
	vec4 group2 = step(shadowmaptc.z, texval( 1.0, -1.0));
	vec4 group3 = step(shadowmaptc.z, texval(-1.0,  1.0));
	vec4 group4 = step(shadowmaptc.z, texval( 1.0,  1.0));
	vec4 cols = vec4(group1.rg, group2.rg) + vec4(group3.ab, group4.ab) +
				mix(vec4(group1.ab, group2.ab), vec4(group3.rg, group4.rg), offset.y);
	f = dot(mix(cols.xyz, cols.yzw, offset.x), vec3(1.0/9.0));
#       endif
#      else
#       ifdef GL_EXT_gpu_shader4
#         define texval(x, y) dp_textureOffset(Texture_ShadowMap2D, center, x, y).r
#       else
#         define texval(x, y) dp_texture2D(Texture_ShadowMap2D, center + vec2(x, y)*ShadowMap_TextureScale.xy).r  
#       endif
#       if USESHADOWMAPPCF > 1
	vec2 center = shadowmaptc.xy - 0.5, offset = fract(center);
	center *= ShadowMap_TextureScale.xy;
	vec4 row1 = step(shadowmaptc.z, vec4(texval(-1.0, -1.0), texval( 0.0, -1.0), texval( 1.0, -1.0), texval( 2.0, -1.0)));
	vec4 row2 = step(shadowmaptc.z, vec4(texval(-1.0,  0.0), texval( 0.0,  0.0), texval( 1.0,  0.0), texval( 2.0,  0.0)));
	vec4 row3 = step(shadowmaptc.z, vec4(texval(-1.0,  1.0), texval( 0.0,  1.0), texval( 1.0,  1.0), texval( 2.0,  1.0)));
	vec4 row4 = step(shadowmaptc.z, vec4(texval(-1.0,  2.0), texval( 0.0,  2.0), texval( 1.0,  2.0), texval( 2.0,  2.0)));
	vec4 cols = row2 + row3 + mix(row1, row4, offset.y);
	f = dot(mix(cols.xyz, cols.yzw, offset.x), vec3(1.0/9.0));
#       else
	vec2 center = shadowmaptc.xy*ShadowMap_TextureScale.xy, offset = fract(shadowmaptc.xy);
	vec3 row1 = step(shadowmaptc.z, vec3(texval(-1.0, -1.0), texval( 0.0, -1.0), texval( 1.0, -1.0)));
	vec3 row2 = step(shadowmaptc.z, vec3(texval(-1.0,  0.0), texval( 0.0,  0.0), texval( 1.0,  0.0)));
	vec3 row3 = step(shadowmaptc.z, vec3(texval(-1.0,  1.0), texval( 0.0,  1.0), texval( 1.0,  1.0)));
	vec3 cols = row2 + mix(row1, row3, offset.y);
	f = dot(mix(cols.xy, cols.yz, offset.x), vec2(0.25));
#       endif
#      endif
#     else
	f = step(shadowmaptc.z, dp_texture2D(Texture_ShadowMap2D, shadowmaptc.xy*ShadowMap_TextureScale.xy).r);
#     endif
#   endif
#  endif
#  ifdef USESHADOWMAPORTHO
	return mix(ShadowMap_Parameters.w, 1.0, f);
#  else
	return f;
#  endif
}
# endif
#endif // !defined(MODE_LIGHTSOURCE) && !defined(MODE_DEFERREDLIGHTSOURCE) && !defined(USESHADOWMAPORTHO)
#endif // FRAGMENT_SHADER




#ifdef MODE_DEFERREDGEOMETRY
#ifdef VERTEX_SHADER
uniform highp mat4 TexMatrix;
#ifdef USEVERTEXTEXTUREBLEND
uniform highp mat4 BackgroundTexMatrix;
#endif
uniform highp mat4 ModelViewMatrix;
void main(void)
{
#ifdef USESKELETAL
	ivec4 si0 = ivec4(Attrib_SkeletalIndex * 3.0);
	ivec4 si1 = si0 + ivec4(1, 1, 1, 1);
	ivec4 si2 = si0 + ivec4(2, 2, 2, 2);
	vec4 sw = Attrib_SkeletalWeight;
	vec4 SkeletalMatrix1 = Skeletal_Transform12[si0.x] * sw.x + Skeletal_Transform12[si0.y] * sw.y + Skeletal_Transform12[si0.z] * sw.z + Skeletal_Transform12[si0.w] * sw.w;
	vec4 SkeletalMatrix2 = Skeletal_Transform12[si1.x] * sw.x + Skeletal_Transform12[si1.y] * sw.y + Skeletal_Transform12[si1.z] * sw.z + Skeletal_Transform12[si1.w] * sw.w;
	vec4 SkeletalMatrix3 = Skeletal_Transform12[si2.x] * sw.x + Skeletal_Transform12[si2.y] * sw.y + Skeletal_Transform12[si2.z] * sw.z + Skeletal_Transform12[si2.w] * sw.w;
	mat4 SkeletalMatrix = mat4(SkeletalMatrix1, SkeletalMatrix2, SkeletalMatrix3, vec4(0.0, 0.0, 0.0, 1.0));
	mat3 SkeletalNormalMatrix = mat3(cross(SkeletalMatrix[1].xyz, SkeletalMatrix[2].xyz), cross(SkeletalMatrix[2].xyz, SkeletalMatrix[0].xyz), cross(SkeletalMatrix[0].xyz, SkeletalMatrix[1].xyz)); // is actually transpose(inverse(mat3(SkeletalMatrix))) * det(mat3(SkeletalMatrix))
	vec4 SkeletalVertex = Attrib_Position * SkeletalMatrix;
	vec3 SkeletalSVector = normalize(Attrib_TexCoord1.xyz * SkeletalNormalMatrix);
	vec3 SkeletalTVector = normalize(Attrib_TexCoord2.xyz * SkeletalNormalMatrix);
	vec3 SkeletalNormal  = normalize(Attrib_TexCoord3.xyz * SkeletalNormalMatrix);
#define Attrib_Position SkeletalVertex
#define Attrib_TexCoord1 SkeletalSVector
#define Attrib_TexCoord2 SkeletalTVector
#define Attrib_TexCoord3 SkeletalNormal
#endif
	TexCoordSurfaceLightmap = vec4((TexMatrix * Attrib_TexCoord0).xy, 0.0, 0.0);
#ifdef USEVERTEXTEXTUREBLEND
	VertexColor = Attrib_Color;
	TexCoord2 = vec2(BackgroundTexMatrix * Attrib_TexCoord0);
#endif

	// transform unnormalized eye direction into tangent space
#ifdef USEOFFSETMAPPING
	vec3 EyeRelative = EyePosition - Attrib_Position.xyz;
	EyeVectorFogDepth.x = dot(EyeRelative, Attrib_TexCoord1.xyz);
	EyeVectorFogDepth.y = dot(EyeRelative, Attrib_TexCoord2.xyz);
	EyeVectorFogDepth.z = dot(EyeRelative, Attrib_TexCoord3.xyz);
	EyeVectorFogDepth.w = 0.0;
#endif

	VectorS = (ModelViewMatrix * vec4(Attrib_TexCoord1.xyz, 0));
	VectorT = (ModelViewMatrix * vec4(Attrib_TexCoord2.xyz, 0));
	VectorR = (ModelViewMatrix * vec4(Attrib_TexCoord3.xyz, 0));
	gl_Position = ModelViewProjectionMatrix * Attrib_Position;
#ifdef USETRIPPY
	gl_Position = TrippyVertex(gl_Position);
#endif
	Depth = (ModelViewMatrix * Attrib_Position).z;
}
#endif // VERTEX_SHADER

#ifdef FRAGMENT_SHADER
void main(void)
{
#ifdef USEOFFSETMAPPING
	// apply offsetmapping
	vec2 dPdx = dp_offsetmapping_dFdx(TexCoordSurfaceLightmap.xy);
	vec2 dPdy = dp_offsetmapping_dFdy(TexCoordSurfaceLightmap.xy);
	vec2 TexCoordOffset = OffsetMapping(TexCoordSurfaceLightmap.xy, dPdx, dPdy);
# define offsetMappedTexture2D(t) dp_textureGrad(t, TexCoordOffset, dPdx, dPdy)
#else
# define offsetMappedTexture2D(t) dp_texture2D(t, TexCoordSurfaceLightmap.xy)
#endif

#ifdef USEALPHAKILL
	if (offsetMappedTexture2D(Texture_Color).a < 0.5)
		discard;
#endif

#ifdef USEVERTEXTEXTUREBLEND
	float alpha = offsetMappedTexture2D(Texture_Color).a;
	float terrainblend = clamp(float(VertexColor.a) * alpha * 2.0 - 0.5, float(0.0), float(1.0));
	//float terrainblend = min(float(VertexColor.a) * alpha * 2.0, float(1.0));
	//float terrainblend = float(VertexColor.a) * alpha > 0.5;
#endif

#ifdef USEVERTEXTEXTUREBLEND
	vec3 surfacenormal = mix(vec3(dp_texture2D(Texture_SecondaryNormal, TexCoord2)), vec3(offsetMappedTexture2D(Texture_Normal)), terrainblend) - vec3(0.5, 0.5, 0.5);
	float a = mix(dp_texture2D(Texture_SecondaryGloss, TexCoord2).a, offsetMappedTexture2D(Texture_Gloss).a, terrainblend);
#else
	vec3 surfacenormal = vec3(offsetMappedTexture2D(Texture_Normal)) - vec3(0.5, 0.5, 0.5);
	float a = offsetMappedTexture2D(Texture_Gloss).a;
#endif

	vec3 pixelnormal = normalize(surfacenormal.x * VectorS.xyz + surfacenormal.y * VectorT.xyz + surfacenormal.z * VectorR.xyz);
	dp_FragColor = vec4(pixelnormal.x, pixelnormal.y, Depth, a);
}
#endif // FRAGMENT_SHADER
#else // !MODE_DEFERREDGEOMETRY




#ifdef MODE_DEFERREDLIGHTSOURCE
#ifdef VERTEX_SHADER
uniform highp mat4 ModelViewMatrix;
void main(void)
{
	ModelViewPosition = ModelViewMatrix * Attrib_Position;
	gl_Position = ModelViewProjectionMatrix * Attrib_Position;
}
#endif // VERTEX_SHADER

#ifdef FRAGMENT_SHADER
uniform highp mat4 ViewToLight;
// ScreenToDepth = vec2(Far / (Far - Near), Far * Near / (Near - Far));
uniform highp vec2 ScreenToDepth;
uniform myhalf3 DeferredColor_Ambient;
uniform myhalf3 DeferredColor_Diffuse;
#ifdef USESPECULAR
uniform myhalf3 DeferredColor_Specular;
uniform myhalf SpecularPower;
#endif
uniform myhalf2 PixelToScreenTexCoord;
void main(void)
{
	// calculate viewspace pixel position
	vec2 ScreenTexCoord = gl_FragCoord.xy * PixelToScreenTexCoord;
	vec3 position;
	// get the geometry information (depth, normal, specular exponent)
	myhalf4 normalmap = dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord);
	// decode viewspace pixel normal
//	myhalf3 surfacenormal = normalize(normalmap.rgb - cast_myhalf3(0.5,0.5,0.5));
	myhalf3 surfacenormal = myhalf3(normalmap.rg, sqrt(1.0-dot(normalmap.rg, normalmap.rg)));
	// decode viewspace pixel position
//	position.z = decodedepthmacro(dp_texture2D(Texture_ScreenDepth, ScreenTexCoord));
	position.z = normalmap.b;
//	position.z = ScreenToDepth.y / (dp_texture2D(Texture_ScreenDepth, ScreenTexCoord).r + ScreenToDepth.x);
	position.xy = ModelViewPosition.xy * (position.z / ModelViewPosition.z);

	// now do the actual shading
	// surfacenormal = pixel normal in viewspace
	// LightVector = pixel to light in viewspace
	// CubeVector = pixel in lightspace
	// eyenormal = pixel to view direction in viewspace
	vec3 CubeVector = vec3(ViewToLight * vec4(position,1));
	myhalf fade = cast_myhalf(dp_texture2D(Texture_Attenuation, vec2(length(CubeVector), 0.0)));
#ifdef USEDIFFUSE
	// calculate diffuse shading
	myhalf3 lightnormal = cast_myhalf3(normalize(LightPosition - position));
SHADEDIFFUSE
#endif
#ifdef USESPECULAR
	// calculate directional shading
	myhalf3 eyenormal = -normalize(cast_myhalf3(position));
SHADESPECULAR(SpecularPower * normalmap.a)
#endif

#if defined(USESHADOWMAP2D)
	fade *= ShadowMapCompare(CubeVector);
#endif

#ifdef USESPECULAR
	gl_FragData[0] = vec4((DeferredColor_Ambient + DeferredColor_Diffuse * diffuse) * fade, 1.0);
	gl_FragData[1] = vec4(DeferredColor_Specular * (specular * fade), 1.0);
# ifdef USECUBEFILTER
	vec3 cubecolor = dp_textureCube(Texture_Cube, CubeVector).rgb;
	gl_FragData[0].rgb *= cubecolor;
	gl_FragData[1].rgb *= cubecolor;
# endif
#else
# ifdef USEDIFFUSE
	gl_FragColor = vec4((DeferredColor_Ambient + DeferredColor_Diffuse * diffuse) * fade, 1.0);
# else
	gl_FragColor = vec4(DeferredColor_Ambient * fade, 1.0);
# endif
# ifdef USECUBEFILTER
	vec3 cubecolor = dp_textureCube(Texture_Cube, CubeVector).rgb;
	gl_FragColor.rgb *= cubecolor;
# endif
#endif
}
#endif // FRAGMENT_SHADER
#else // !MODE_DEFERREDLIGHTSOURCE




#ifdef VERTEX_SHADER
uniform highp mat4 TexMatrix;
#ifdef USEVERTEXTEXTUREBLEND
uniform highp mat4 BackgroundTexMatrix;
#endif
#ifdef MODE_LIGHTSOURCE
uniform highp mat4 ModelToLight;
#endif
#ifdef USESHADOWMAPORTHO
uniform highp mat4 ShadowMapMatrix;
#endif
#ifdef MODE_LIGHTGRID
uniform highp mat4 LightGridMatrix;
#endif
#ifdef USEBOUNCEGRID
uniform highp mat4 BounceGridMatrix;
#endif
void main(void)
{
#ifdef USESKELETAL
	ivec4 si0 = ivec4(Attrib_SkeletalIndex * 3.0);
	ivec4 si1 = si0 + ivec4(1, 1, 1, 1);
	ivec4 si2 = si0 + ivec4(2, 2, 2, 2);
	vec4 sw = Attrib_SkeletalWeight;
	vec4 SkeletalMatrix1 = Skeletal_Transform12[si0.x] * sw.x + Skeletal_Transform12[si0.y] * sw.y + Skeletal_Transform12[si0.z] * sw.z + Skeletal_Transform12[si0.w] * sw.w;
	vec4 SkeletalMatrix2 = Skeletal_Transform12[si1.x] * sw.x + Skeletal_Transform12[si1.y] * sw.y + Skeletal_Transform12[si1.z] * sw.z + Skeletal_Transform12[si1.w] * sw.w;
	vec4 SkeletalMatrix3 = Skeletal_Transform12[si2.x] * sw.x + Skeletal_Transform12[si2.y] * sw.y + Skeletal_Transform12[si2.z] * sw.z + Skeletal_Transform12[si2.w] * sw.w;
	mat4 SkeletalMatrix = mat4(SkeletalMatrix1, SkeletalMatrix2, SkeletalMatrix3, vec4(0.0, 0.0, 0.0, 1.0));
//	ivec4 si = ivec4(Attrib_SkeletalIndex);
//	mat4 SkeletalMatrix = Skeletal_Transform[si.x] * Attrib_SkeletalWeight.x + Skeletal_Transform[si.y] * Attrib_SkeletalWeight.y + Skeletal_Transform[si.z] * Attrib_SkeletalWeight.z + Skeletal_Transform[si.w] * Attrib_SkeletalWeight.w;
	mat3 SkeletalNormalMatrix = mat3(cross(SkeletalMatrix[1].xyz, SkeletalMatrix[2].xyz), cross(SkeletalMatrix[2].xyz, SkeletalMatrix[0].xyz), cross(SkeletalMatrix[0].xyz, SkeletalMatrix[1].xyz)); // is actually transpose(inverse(mat3(SkeletalMatrix))) * det(mat3(SkeletalMatrix))
	vec4 SkeletalVertex = Attrib_Position * SkeletalMatrix;
	SkeletalVertex.w = 1.0;
	vec3 SkeletalSVector = normalize(Attrib_TexCoord1.xyz * SkeletalNormalMatrix);
	vec3 SkeletalTVector = normalize(Attrib_TexCoord2.xyz * SkeletalNormalMatrix);
	vec3 SkeletalNormal  = normalize(Attrib_TexCoord3.xyz * SkeletalNormalMatrix);
#define Attrib_Position SkeletalVertex
#define Attrib_TexCoord1 SkeletalSVector
#define Attrib_TexCoord2 SkeletalTVector
#define Attrib_TexCoord3 SkeletalNormal
#endif

#if defined(MODE_VERTEXCOLOR) || defined(USEVERTEXTEXTUREBLEND) || defined(MODE_LIGHTDIRECTIONMAP_FORCED_VERTEXCOLOR) || defined(USEALPHAGENVERTEX)
	VertexColor = Attrib_Color;
#endif
	// copy the surface texcoord
#ifdef USELIGHTMAP
	TexCoordSurfaceLightmap = vec4((TexMatrix * Attrib_TexCoord0).xy, Attrib_TexCoord4.xy);
#else
	TexCoordSurfaceLightmap = vec4((TexMatrix * Attrib_TexCoord0).xy, 0.0, 0.0);
#endif
#ifdef USEVERTEXTEXTUREBLEND
	TexCoord2 = vec2(BackgroundTexMatrix * Attrib_TexCoord0);
#endif

#ifdef MODE_LIGHTGRID
	LightGridTC = vec3(LightGridMatrix * Attrib_Position);
#endif
#ifdef USEBOUNCEGRID
	BounceGridTexCoord = vec3(BounceGridMatrix * Attrib_Position);
#ifdef USEBOUNCEGRIDDIRECTIONAL
	BounceGridTexCoord.z *= 0.125;
#endif
#endif

#ifdef MODE_LIGHTSOURCE
	// transform vertex position into light attenuation/cubemap space
	// (-1 to +1 across the light box)
	CubeVector = vec3(ModelToLight * Attrib_Position);

# ifdef USEDIFFUSE
	// transform unnormalized light direction into tangent space
	// (we use unnormalized to ensure that it interpolates correctly and then
	//  normalize it per pixel)
	vec3 lightminusvertex = LightPosition - Attrib_Position.xyz;
	LightVector.x = dot(lightminusvertex, Attrib_TexCoord1.xyz);
	LightVector.y = dot(lightminusvertex, Attrib_TexCoord2.xyz);
	LightVector.z = dot(lightminusvertex, Attrib_TexCoord3.xyz);
# endif
#endif

#if defined(MODE_LIGHTDIRECTION) && defined(USEDIFFUSE)
	LightVector.x = dot(LightDir, Attrib_TexCoord1.xyz);
	LightVector.y = dot(LightDir, Attrib_TexCoord2.xyz);
	LightVector.z = dot(LightDir, Attrib_TexCoord3.xyz);
#endif

	// transform unnormalized eye direction into tangent space
#ifdef USEEYEVECTOR
	vec3 EyeRelative = EyePosition - Attrib_Position.xyz;
	EyeVectorFogDepth.x = dot(EyeRelative, Attrib_TexCoord1.xyz);
	EyeVectorFogDepth.y = dot(EyeRelative, Attrib_TexCoord2.xyz);
	EyeVectorFogDepth.z = dot(EyeRelative, Attrib_TexCoord3.xyz);
#ifdef USEFOG
	EyeVectorFogDepth.w = dot(FogPlane, Attrib_Position);
#else
	EyeVectorFogDepth.w = 0.0;
#endif
#endif


#if defined(MODE_LIGHTDIRECTIONMAP_MODELSPACE) || defined(USEREFLECTCUBE) || defined(USEBOUNCEGRIDDIRECTIONAL) || defined(MODE_LIGHTGRID)
# ifdef USEFOG
	vec3 EyeDir = EyePosition - Attrib_Position.xyz;
	VectorS = vec4(Attrib_TexCoord1.xyz, EyeDir.x);
	VectorT = vec4(Attrib_TexCoord2.xyz, EyeDir.y);
	VectorR = vec4(Attrib_TexCoord3.xyz, EyeDir.z);
# else
	VectorS = vec4(Attrib_TexCoord1, 0);
	VectorT = vec4(Attrib_TexCoord2, 0);
	VectorR = vec4(Attrib_TexCoord3, 0);
# endif
#else
# ifdef USEFOG
	EyeVectorModelSpace = EyePosition - Attrib_Position.xyz;
# endif
#endif

	// transform vertex to clipspace (post-projection, but before perspective divide by W occurs)
	gl_Position = ModelViewProjectionMatrix * Attrib_Position;

#ifdef USESHADOWMAPORTHO
	ShadowMapTC = vec3(ShadowMapMatrix * gl_Position);
#endif

#ifdef USEREFLECTION
	ModelViewProjectionPosition = gl_Position;
#endif
#ifdef USETRIPPY
	gl_Position = TrippyVertex(gl_Position);
#endif
}
#endif // VERTEX_SHADER




#ifdef FRAGMENT_SHADER
#ifdef USEDEFERREDLIGHTMAP
uniform myhalf2 PixelToScreenTexCoord;
uniform myhalf3 DeferredMod_Diffuse;
uniform myhalf3 DeferredMod_Specular;
#endif
uniform myhalf3 Color_Ambient;
uniform myhalf3 Color_Diffuse;
uniform myhalf3 Color_Specular;
uniform myhalf SpecularPower;
#ifdef USEGLOW
uniform myhalf3 Color_Glow;
#endif
uniform myhalf Alpha;
#ifdef USEREFLECTION
uniform mediump vec4 DistortScaleRefractReflect;
uniform mediump vec4 ScreenScaleRefractReflect;
uniform mediump vec4 ScreenCenterRefractReflect;
uniform mediump vec4 ReflectColor;
#endif
#ifdef USEREFLECTCUBE
uniform highp mat4 ModelToReflectCube;
uniform sampler2D Texture_ReflectMask;
uniform samplerCube Texture_ReflectCube;
#endif
#ifdef MODE_LIGHTGRID
uniform sampler3D Texture_LightGrid;
uniform mat3 LightGridNormalMatrix;
#endif
#ifdef USEBOUNCEGRID
uniform sampler3D Texture_BounceGrid;
uniform float BounceGridIntensity;
uniform highp mat4 BounceGridMatrix;
#endif
uniform highp float ClientTime;
#ifdef USENORMALMAPSCROLLBLEND
uniform highp vec2 NormalmapScrollBlend;
#endif
#ifdef USEOCCLUDE
uniform occludeQuery {
    uint visiblepixels;
    uint allpixels;
};
#endif
void main(void)
{
#ifdef USEOFFSETMAPPING
	// apply offsetmapping
	vec2 dPdx = dp_offsetmapping_dFdx(TexCoordSurfaceLightmap.xy);
	vec2 dPdy = dp_offsetmapping_dFdy(TexCoordSurfaceLightmap.xy);
	vec2 TexCoordOffset = OffsetMapping(TexCoordSurfaceLightmap.xy, dPdx, dPdy);
# define offsetMappedTexture2D(t) dp_textureGrad(t, TexCoordOffset, dPdx, dPdy)
# define TexCoord TexCoordOffset
#else
# define offsetMappedTexture2D(t) dp_texture2D(t, TexCoordSurfaceLightmap.xy)
# define TexCoord TexCoordSurfaceLightmap.xy
#endif

	// combine the diffuse textures (base, pants, shirt)
	myhalf4 color = cast_myhalf4(offsetMappedTexture2D(Texture_Color));
#ifdef USEALPHAKILL
	if (color.a < 0.5)
		discard;
#endif
	color.a *= Alpha;
#ifdef USECOLORMAPPING
	color.rgb += cast_myhalf3(offsetMappedTexture2D(Texture_Pants)) * Color_Pants + cast_myhalf3(offsetMappedTexture2D(Texture_Shirt)) * Color_Shirt;
#endif
#ifdef USEVERTEXTEXTUREBLEND
#ifdef USEBOTHALPHAS
	myhalf4 color2 = cast_myhalf4(dp_texture2D(Texture_SecondaryColor, TexCoord2));
	myhalf terrainblend = max(sat(cast_myhalf(VertexColor.a) * color.a), cast_myhalf(1.0 - color2.a));
	color.rgb = mix(color2.rgb, color.rgb, terrainblend);
#else
	myhalf terrainblend = sat(cast_myhalf(VertexColor.a) * color.a * 2.0 - 0.5);
	//myhalf terrainblend = min(cast_myhalf(VertexColor.a) * color.a * 2.0, cast_myhalf(1.0));
	//myhalf terrainblend = cast_myhalf(VertexColor.a) * color.a > 0.5;
	color.rgb = mix(cast_myhalf3(dp_texture2D(Texture_SecondaryColor, TexCoord2)), color.rgb, terrainblend);
#endif
	color.a = 1.0;
	//color = mix(cast_myhalf4(1, 0, 0, 1), color, terrainblend);
#endif
#ifdef USEALPHAGENVERTEX
	color.a *= VertexColor.a;
#endif

	// get the surface normal
#ifdef USEVERTEXTEXTUREBLEND
	myhalf3 surfacenormal = normalize(mix(cast_myhalf3(dp_texture2D(Texture_SecondaryNormal, TexCoord2)), cast_myhalf3(offsetMappedTexture2D(Texture_Normal)), terrainblend) - cast_myhalf3(0.5, 0.5, 0.5));
#else
	myhalf3 surfacenormal = normalize(cast_myhalf3(offsetMappedTexture2D(Texture_Normal)) - cast_myhalf3(0.5, 0.5, 0.5));
#endif

	// get the material colors
	myhalf3 diffusetex = color.rgb;
#if defined(USESPECULAR) || defined(USEDEFERREDLIGHTMAP)
# ifdef USEVERTEXTEXTUREBLEND
	myhalf4 glosstex = mix(cast_myhalf4(dp_texture2D(Texture_SecondaryGloss, TexCoord2)), cast_myhalf4(offsetMappedTexture2D(Texture_Gloss)), terrainblend);
# else
	myhalf4 glosstex = cast_myhalf4(offsetMappedTexture2D(Texture_Gloss));
# endif
#endif

#ifdef USEREFLECTCUBE
	vec3 TangentReflectVector = reflect(-EyeVectorFogDepth.xyz, surfacenormal);
	vec3 ModelReflectVector = TangentReflectVector.x * VectorS.xyz + TangentReflectVector.y * VectorT.xyz + TangentReflectVector.z * VectorR.xyz;
	vec3 ReflectCubeTexCoord = vec3(ModelToReflectCube * vec4(ModelReflectVector, 0));
	diffusetex += cast_myhalf3(offsetMappedTexture2D(Texture_ReflectMask)) * cast_myhalf3(dp_textureCube(Texture_ReflectCube, ReflectCubeTexCoord));
#endif

#ifdef USESPECULAR
	myhalf3 eyenormal = normalize(cast_myhalf3(EyeVectorFogDepth.xyz));
#endif




#ifdef MODE_LIGHTSOURCE
	// light source
#ifdef USEDIFFUSE
	myhalf3 lightnormal = cast_myhalf3(normalize(LightVector));
SHADEDIFFUSE
	color.rgb = diffusetex * (Color_Ambient + diffuse * Color_Diffuse);
#ifdef USESPECULAR
SHADESPECULAR(SpecularPower * glosstex.a)
	color.rgb += glosstex.rgb * (specular * Color_Specular);
#endif
#else
	color.rgb = diffusetex * Color_Ambient;
#endif
	color.rgb *= cast_myhalf(dp_texture2D(Texture_Attenuation, vec2(length(CubeVector), 0.0)));
#if defined(USESHADOWMAP2D)
	color.rgb *= ShadowMapCompare(CubeVector);
#endif
# ifdef USECUBEFILTER
	color.rgb *= cast_myhalf3(dp_textureCube(Texture_Cube, CubeVector));
# endif
#endif // MODE_LIGHTSOURCE




#ifdef MODE_LIGHTGRID
	// clamp the LightGrid TC Z coordinate to the first of the 3 layers, to
	// prevent repeat-artifacts for lightgrids smaller than the visible scene
	// (which is often the case - the lightgrid bounds is defined by the level
	// designer and usually matches the playable area, not the scenery around
	// it), we can rely on GL_CLAMP_TO_EDGE for this in all other directions.
	vec3 LGTC = vec3(LightGridTC.xy, min(LightGridTC.z, 0.333333));
	myhalf3 ambientcolor = cast_myhalf3(dp_texture2D(Texture_LightGrid, LGTC));
	myhalf3 lightcolor = cast_myhalf3(dp_texture2D(Texture_LightGrid, LGTC + vec3(0, 0, 0.333333)));
	myhalf3 lightnormal_worldspace = cast_myhalf3(dp_texture2D(Texture_LightGrid, LGTC + vec3(0, 0, 0.6666667))) * 2.0 + cast_myhalf3(-1.0, -1.0, -1.0);
	myhalf3 lightnormal_modelspace = cast_myhalf3(lightnormal_worldspace * LightGridNormalMatrix);
	// convert modelspace light vector to tangentspace
	myhalf3 lightnormal;
	lightnormal.x = dot(lightnormal_modelspace, cast_myhalf3(VectorS));
	lightnormal.y = dot(lightnormal_modelspace, cast_myhalf3(VectorT));
	lightnormal.z = dot(lightnormal_modelspace, cast_myhalf3(VectorR));
	lightnormal = normalize(lightnormal); // VectorS/T/R are not always perfectly normalized, and EXACTSPECULARMATH is very picky about this
	// now we have the light parameters, so do the shading...
SHADEDIFFUSE
	color.rgb = diffusetex * (Color_Ambient + Color_Diffuse * (ambientcolor + diffuse * lightcolor));
#ifdef USESPECULAR
SHADESPECULAR(SpecularPower * glosstex.a)
	color.rgb += glosstex.rgb * (specular * Color_Specular * lightcolor);
#endif
#endif



#ifdef MODE_LIGHTDIRECTION
	#define SHADING
	#ifdef USEDIFFUSE
		myhalf3 lightnormal = cast_myhalf3(normalize(LightVector));
	#endif
	#define lightcolor 1
#endif // MODE_LIGHTDIRECTION
#ifdef MODE_LIGHTDIRECTIONMAP_MODELSPACE
   #define SHADING
	// deluxemap lightmapping using light vectors in modelspace (q3map2 -light -deluxe)
	myhalf3 lightnormal_modelspace = cast_myhalf3(dp_texture2D(Texture_Deluxemap, TexCoordSurfaceLightmap.zw)) * 2.0 + cast_myhalf3(-1.0, -1.0, -1.0);
	myhalf3 lightcolor = cast_myhalf3(dp_texture2D(Texture_Lightmap, TexCoordSurfaceLightmap.zw));
	// convert modelspace light vector to tangentspace
	myhalf3 lightnormal;
	lightnormal.x = dot(lightnormal_modelspace, cast_myhalf3(VectorS));
	lightnormal.y = dot(lightnormal_modelspace, cast_myhalf3(VectorT));
	lightnormal.z = dot(lightnormal_modelspace, cast_myhalf3(VectorR));
	lightnormal = normalize(lightnormal); // VectorS/T/R are not always perfectly normalized, and EXACTSPECULARMATH is very picky about this
	// calculate directional shading (and undoing the existing angle attenuation on the lightmap by the division)
	// note that q3map2 is too stupid to calculate proper surface normals when q3map_nonplanar
	// is used (the lightmap and deluxemap coords correspond to virtually random coordinates
	// on that luxel, and NOT to its center, because recursive triangle subdivision is used
	// to map the luxels to coordinates on the draw surfaces), which also causes
	// deluxemaps to be wrong because light contributions from the wrong side of the surface
	// are added up. To prevent divisions by zero or strong exaggerations, a max()
	// nudge is done here at expense of some additional fps. This is ONLY needed for
	// deluxemaps, tangentspace deluxemap avoid this problem by design.
	lightcolor *= 1.0 / max(0.25, lightnormal.z);
#endif // MODE_LIGHTDIRECTIONMAP_MODELSPACE
#ifdef MODE_LIGHTDIRECTIONMAP_TANGENTSPACE
   #define SHADING
	// deluxemap lightmapping using light vectors in tangentspace (hmap2 -light)
	myhalf3 lightnormal = cast_myhalf3(dp_texture2D(Texture_Deluxemap, TexCoordSurfaceLightmap.zw)) * 2.0 + cast_myhalf3(-1.0, -1.0, -1.0);
	myhalf3 lightcolor = cast_myhalf3(dp_texture2D(Texture_Lightmap, TexCoordSurfaceLightmap.zw));
#endif
#if defined(MODE_LIGHTDIRECTIONMAP_FORCED_LIGHTMAP) || defined(MODE_LIGHTDIRECTIONMAP_FORCED_VERTEXCOLOR)
	#define SHADING
	// forced deluxemap on lightmapped/vertexlit surfaces
	myhalf3 lightnormal = cast_myhalf3(0.0, 0.0, 1.0);
   #ifdef USELIGHTMAP
		myhalf3 lightcolor = cast_myhalf3(dp_texture2D(Texture_Lightmap, TexCoordSurfaceLightmap.zw));
   #else
		myhalf3 lightcolor = cast_myhalf3(VertexColor.rgb);
   #endif
#endif




#ifdef MODE_LIGHTMAP
	color.rgb = diffusetex * (Color_Ambient + cast_myhalf3(dp_texture2D(Texture_Lightmap, TexCoordSurfaceLightmap.zw)) * Color_Diffuse);
#endif // MODE_LIGHTMAP
#ifdef MODE_VERTEXCOLOR
	color.rgb = diffusetex * (Color_Ambient + cast_myhalf3(VertexColor.rgb) * Color_Diffuse);
#endif // MODE_VERTEXCOLOR
#ifdef MODE_FLATCOLOR
	color.rgb = diffusetex * Color_Ambient;
#endif // MODE_FLATCOLOR




#ifdef SHADING
# ifdef USEDIFFUSE
SHADEDIFFUSE
#  ifdef USESPECULAR
SHADESPECULAR(SpecularPower * glosstex.a)
	color.rgb = diffusetex * Color_Ambient + (diffusetex * Color_Diffuse * diffuse + glosstex.rgb * Color_Specular * specular) * lightcolor;
#  else
	color.rgb = diffusetex * (Color_Ambient + Color_Diffuse * diffuse * lightcolor);
#  endif
# else
	color.rgb = diffusetex * Color_Ambient;
# endif
#endif

#ifdef USESHADOWMAPORTHO
	color.rgb *= ShadowMapCompare(ShadowMapTC);
#endif

#ifdef USEDEFERREDLIGHTMAP
	vec2 ScreenTexCoord = gl_FragCoord.xy * PixelToScreenTexCoord;
	color.rgb += diffusetex * cast_myhalf3(dp_texture2D(Texture_ScreenDiffuse, ScreenTexCoord)) * DeferredMod_Diffuse;
	color.rgb += glosstex.rgb * cast_myhalf3(dp_texture2D(Texture_ScreenSpecular, ScreenTexCoord)) * DeferredMod_Specular;
//	color.rgb = dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord).rgb * vec3(1.0, 1.0, 0.001);
#endif

#ifdef USEBOUNCEGRID
#ifdef USEBOUNCEGRIDDIRECTIONAL
//	myhalf4 bouncegrid_coeff1 = cast_myhalf4(dp_texture3D(Texture_BounceGrid, BounceGridTexCoord                        ));
//	myhalf4 bouncegrid_coeff2 = cast_myhalf4(dp_texture3D(Texture_BounceGrid, BounceGridTexCoord + vec3(0.0, 0.0, 0.125))) * 2.0 + cast_myhalf4(-1.0, -1.0, -1.0, -1.0);
	myhalf4 bouncegrid_coeff3 = cast_myhalf4(dp_texture3D(Texture_BounceGrid, BounceGridTexCoord + vec3(0.0, 0.0, 0.250)));
	myhalf4 bouncegrid_coeff4 = cast_myhalf4(dp_texture3D(Texture_BounceGrid, BounceGridTexCoord + vec3(0.0, 0.0, 0.375)));
	myhalf4 bouncegrid_coeff5 = cast_myhalf4(dp_texture3D(Texture_BounceGrid, BounceGridTexCoord + vec3(0.0, 0.0, 0.500)));
	myhalf4 bouncegrid_coeff6 = cast_myhalf4(dp_texture3D(Texture_BounceGrid, BounceGridTexCoord + vec3(0.0, 0.0, 0.625)));
	myhalf4 bouncegrid_coeff7 = cast_myhalf4(dp_texture3D(Texture_BounceGrid, BounceGridTexCoord + vec3(0.0, 0.0, 0.750)));
	myhalf4 bouncegrid_coeff8 = cast_myhalf4(dp_texture3D(Texture_BounceGrid, BounceGridTexCoord + vec3(0.0, 0.0, 0.875)));
	myhalf3 bouncegrid_dir = normalize(mat3(BounceGridMatrix) * (surfacenormal.x * VectorS.xyz + surfacenormal.y * VectorT.xyz + surfacenormal.z * VectorR.xyz));
	myhalf3 bouncegrid_dirp = possat(bouncegrid_dir);
	myhalf3 bouncegrid_dirn = possat(-bouncegrid_dir);
//	bouncegrid_dirp  = bouncegrid_dirn = cast_myhalf3(1.0,1.0,1.0);
	myhalf3 bouncegrid_light = cast_myhalf3(
		dot(bouncegrid_coeff3.xyz, bouncegrid_dirp) + dot(bouncegrid_coeff6.xyz, bouncegrid_dirn),
		dot(bouncegrid_coeff4.xyz, bouncegrid_dirp) + dot(bouncegrid_coeff7.xyz, bouncegrid_dirn),
		dot(bouncegrid_coeff5.xyz, bouncegrid_dirp) + dot(bouncegrid_coeff8.xyz, bouncegrid_dirn));
	color.rgb += diffusetex * bouncegrid_light * BounceGridIntensity;
//	color.rgb = bouncegrid_dir.rgb * 0.5 + vec3(0.5, 0.5, 0.5);
#else
	color.rgb += diffusetex * cast_myhalf3(dp_texture3D(Texture_BounceGrid, BounceGridTexCoord)) * BounceGridIntensity;
#endif
#endif

#ifdef USEGLOW
#ifdef USEVERTEXTEXTUREBLEND
	color.rgb += mix(cast_myhalf3(dp_texture2D(Texture_SecondaryGlow, TexCoord2)), cast_myhalf3(offsetMappedTexture2D(Texture_Glow)), terrainblend) * Color_Glow;
#else
	color.rgb += cast_myhalf3(offsetMappedTexture2D(Texture_Glow)) * Color_Glow;
#endif
#endif

#ifdef USECELOUTLINES
# ifdef USEDEFERREDLIGHTMAP
//	vec2 ScreenTexCoord = gl_FragCoord.xy * PixelToScreenTexCoord;
	vec4 ScreenTexCoordStep = vec4(PixelToScreenTexCoord.x, 0.0, 0.0, PixelToScreenTexCoord.y);
	vec4 DepthNeighbors;

	// enable to test ink on white geometry
//	color.rgb = vec3(1.0, 1.0, 1.0);

	// note: this seems to be negative
	float DepthCenter = dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord).b;

	// edge detect method
//	DepthNeighbors.x = dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord - ScreenTexCoordStep.xy).b;
//	DepthNeighbors.y = dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + ScreenTexCoordStep.xy).b;
//	DepthNeighbors.z = dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + ScreenTexCoordStep.zw).b;
//	DepthNeighbors.w = dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord - ScreenTexCoordStep.zw).b;
//	float DepthAverage = dot(DepthNeighbors, vec4(0.25, 0.25, 0.25, 0.25));
//	float DepthDelta = abs(dot(DepthNeighbors.xy, vec2(-1.0, 1.0))) + abs(dot(DepthNeighbors.zw, vec2(-1.0, 1.0)));
//	color.rgb *= max(0.5, 1.0 - max(0.0, abs(DepthCenter - DepthAverage) - 0.2 * DepthDelta) / (0.01 + 0.2 * DepthDelta));
//	color.rgb *= step(abs(DepthCenter - DepthAverage), 0.2 * DepthDelta); 

	// shadow method
	float DepthScale1 = 4.0 / DepthCenter; // inner ink (shadow on object)
//	float DepthScale1 = -4.0 / DepthCenter; // outer ink (shadow around object)
//	float DepthScale1 = 0.003;
	float DepthScale2 = DepthScale1 * 0.5;
//	float DepthScale3 = DepthScale1 / 4.0;
	float DepthBias1 = -DepthCenter * DepthScale1;
	float DepthBias2 = -DepthCenter * DepthScale2;
//	float DepthBias3 = -DepthCenter * DepthScale3;
	float DepthShadow = possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2(-1.0,  0.0)).b * DepthScale1 + DepthBias1)
	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2( 1.0,  0.0)).b * DepthScale1 + DepthBias1)
	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2( 0.0, -1.0)).b * DepthScale1 + DepthBias1)
	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2( 0.0,  1.0)).b * DepthScale1 + DepthBias1)
	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2(-2.0,  0.0)).b * DepthScale2 + DepthBias2)
	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2( 2.0,  0.0)).b * DepthScale2 + DepthBias2)
	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2( 0.0, -2.0)).b * DepthScale2 + DepthBias2)
	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2( 0.0,  2.0)).b * DepthScale2 + DepthBias2)
//	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2(-3.0,  0.0)).b * DepthScale3 + DepthBias3)
//	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2( 3.0,  0.0)).b * DepthScale3 + DepthBias3)
//	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2( 0.0, -3.0)).b * DepthScale3 + DepthBias3)
//	                  + possat(dp_texture2D(Texture_ScreenNormalMap, ScreenTexCoord + PixelToScreenTexCoord * vec2( 0.0,  3.0)).b * DepthScale3 + DepthBias3)
	                  - 0.0;
	color.rgb *= sat(1.0 - DepthShadow);
//	color.r = DepthCenter / -1024.0;
# endif
#endif

#ifdef USEFOG
	color.rgb = FogVertex(color);
#endif

	// reflection must come last because it already contains exactly the correct fog (the reflection render preserves camera distance from the plane, it only flips the side) and ContrastBoost/SceneBrightness
#ifdef USEREFLECTION
	vec4 ScreenScaleRefractReflectIW = ScreenScaleRefractReflect * (1.0 / ModelViewProjectionPosition.w);
	//vec4 ScreenTexCoord = (ModelViewProjectionPosition.xyxy + normalize(cast_myhalf3(offsetMappedTexture2D(Texture_Normal)) - cast_myhalf3(0.5)).xyxy * DistortScaleRefractReflect * 100) * ScreenScaleRefractReflectIW + ScreenCenterRefractReflect;
	vec2 SafeScreenTexCoord = ModelViewProjectionPosition.xy * ScreenScaleRefractReflectIW.zw + ScreenCenterRefractReflect.zw;
	#ifdef USENORMALMAPSCROLLBLEND
# ifdef USEOFFSETMAPPING
		vec3 normal = dp_textureGrad(Texture_Normal, (TexCoord + vec2(0.08, 0.08)*ClientTime*NormalmapScrollBlend.x*0.5)*NormalmapScrollBlend.y, dPdx*NormalmapScrollBlend.y, dPdy*NormalmapScrollBlend.y).rgb - vec3(1.0);
# else
		vec3 normal = dp_texture2D(Texture_Normal, (TexCoord + vec2(0.08, 0.08)*ClientTime*NormalmapScrollBlend.x*0.5)*NormalmapScrollBlend.y).rgb - vec3(1.0);
# endif
		normal += dp_texture2D(Texture_Normal, (TexCoord + vec2(-0.06, -0.09)*ClientTime*NormalmapScrollBlend.x)*NormalmapScrollBlend.y*0.75).rgb;
		vec2 ScreenTexCoord = SafeScreenTexCoord + vec3(normalize(cast_myhalf3(normal))).xy * DistortScaleRefractReflect.zw;
	#else
		vec2 ScreenTexCoord = SafeScreenTexCoord + vec3(normalize(cast_myhalf3(offsetMappedTexture2D(Texture_Normal)) - cast_myhalf3(0.5))).xy * DistortScaleRefractReflect.zw;
	#endif
	// FIXME temporary hack to detect the case that the reflection
	// gets blackened at edges due to leaving the area that contains actual
	// content.
	// Remove this 'ack once we have a better way to stop this thing from
	// 'appening.
	float f = minonesat(length(dp_texture2D(Texture_Reflection, ScreenTexCoord + vec2(0.01, 0.01)).rgb) / 0.05);
	f      *= minonesat(length(dp_texture2D(Texture_Reflection, ScreenTexCoord + vec2(0.01, -0.01)).rgb) / 0.05);
	f      *= minonesat(length(dp_texture2D(Texture_Reflection, ScreenTexCoord + vec2(-0.01, 0.01)).rgb) / 0.05);
	f      *= minonesat(length(dp_texture2D(Texture_Reflection, ScreenTexCoord + vec2(-0.01, -0.01)).rgb) / 0.05);
	ScreenTexCoord = mix(SafeScreenTexCoord, ScreenTexCoord, f);
	color.rgb = mix(color.rgb, cast_myhalf3(dp_texture2D(Texture_Reflection, ScreenTexCoord)) * ReflectColor.rgb, ReflectColor.a);
#endif
#ifdef USEOCCLUDE
   color.rgb *= clamp(float(visiblepixels) / float(allpixels), 0.0, 1.0);
#endif

	dp_FragColor = vec4(color);
}
#endif // FRAGMENT_SHADER

#endif // !MODE_DEFERREDLIGHTSOURCE
#endif // !MODE_DEFERREDGEOMETRY
#endif // !MODE_WATER
#endif // !MODE_REFRACTION
#endif // !MODE_BLOOMBLUR
#endif // !MODE_GENERIC
#endif // !MODE_POSTPROCESS
#endif // !MODE_DEPTH_OR_SHADOW
