/**
 * AmbientShader — WebGL generative visual background for Hapax Corpora.
 *
 * Ports agents/shaders/ambient_fbm.frag to WebGL 1.0. Single fullscreen
 * quad + fragment shader. No Three.js. Self-throttled FPS based on display
 * state: ambient=15, informational=30, performative=60.
 *
 * Warm color palette only (never blue/white): deep ember -> burnt orange -> dark.
 */

import { useEffect, useRef, useCallback } from "react";

interface AmbientShaderProps {
  speed: number;
  turbulence: number;
  warmth: number;
  brightness: number;
  displayState: string;
}

const VERTEX_SHADER = `
attribute vec2 a_position;
varying vec2 v_uv;
void main() {
  v_uv = a_position * 0.5 + 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER = `
precision mediump float;
varying vec2 v_uv;
uniform float u_time;
uniform float u_speed;
uniform float u_turbulence;
uniform float u_warmth;
uniform float u_brightness;
uniform float u_lod;
uniform vec2 u_resolution;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash(i + vec2(0.0, 0.0)), hash(i + vec2(1.0, 0.0)), u.x),
    mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
    u.y
  );
}

float fbm(vec2 p, float turb) {
  int octaves = int(u_lod + turb * (6.0 - u_lod));
  float value = 0.0;
  float amplitude = 0.5;
  float frequency = 1.0;
  for (int i = 0; i < 6; i++) {
    if (i >= octaves) break;
    value += amplitude * noise(p * frequency);
    frequency *= 2.0;
    amplitude *= 0.5;
  }
  return value;
}

void main() {
  vec2 uv = v_uv;
  // Aspect ratio correction
  float aspect = u_resolution.x / u_resolution.y;
  vec2 scaled_uv = vec2(uv.x * aspect, uv.y);

  float spd = max(u_speed, 0.01);
  float t = u_time * spd * 0.3;

  // Flow field with noise offset for organic movement
  vec2 flow_uv = scaled_uv * 3.0 + vec2(t * 0.7, t * 0.5);
  float turb = max(u_turbulence, 0.05);
  float flow1 = fbm(flow_uv, turb);
  float flow2 = fbm(flow_uv + vec2(5.2, 1.3) + t * 0.2, turb);

  // Color: warm spectrum only — deep ember to burnt orange
  // Never blue/white
  vec3 deep = vec3(0.06, 0.02, 0.01);    // near-black warm
  vec3 ember = vec3(0.25, 0.08, 0.03);   // dark ember
  vec3 orange = vec3(0.40, 0.15, 0.05);  // burnt orange

  vec3 base = mix(deep, ember, u_warmth);
  vec3 highlight = mix(ember, orange, u_warmth);

  // Apply noise as luminance and color variation
  float lum = flow1 * 0.6 + flow2 * 0.4;
  lum = lum * u_brightness;

  vec3 color = mix(base, highlight, lum);

  // Subtle vignette
  float vignette = 1.0 - length((uv - 0.5) * 1.5);
  vignette = smoothstep(0.0, 0.7, vignette);
  color *= vignette;

  gl_FragColor = vec4(color, 1.0);
}
`;

function targetFPS(displayState: string): number {
  switch (displayState) {
    case "performative":
      return 60;
    case "informational":
    case "alert":
      return 30;
    default:
      return 15;
  }
}

function lodForState(displayState: string): number {
  switch (displayState) {
    case "performative":
      return 4.0;
    case "informational":
    case "alert":
      return 3.0;
    default:
      return 2.0;
  }
}

function resolutionScale(displayState: string): number {
  switch (displayState) {
    case "performative":
      return 1.0;
    case "informational":
    case "alert":
      return 0.75;
    default:
      return 0.5;
  }
}

export function AmbientShader({
  speed,
  turbulence,
  warmth,
  brightness,
  displayState,
}: AmbientShaderProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const glRef = useRef<WebGLRenderingContext | null>(null);
  const programRef = useRef<WebGLProgram | null>(null);
  const uniformsRef = useRef<Record<string, WebGLUniformLocation | null>>({});
  const rafRef = useRef<number>(0);
  const startTimeRef = useRef<number>(performance.now());

  const initGL = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext("webgl", {
      alpha: false,
      antialias: false,
      preserveDrawingBuffer: false,
    });
    if (!gl) return;

    glRef.current = gl;

    // Compile shaders
    const vs = gl.createShader(gl.VERTEX_SHADER)!;
    gl.shaderSource(vs, VERTEX_SHADER);
    gl.compileShader(vs);

    const fs = gl.createShader(gl.FRAGMENT_SHADER)!;
    gl.shaderSource(fs, FRAGMENT_SHADER);
    gl.compileShader(fs);

    const program = gl.createProgram()!;
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    gl.useProgram(program);
    programRef.current = program;

    // Fullscreen quad
    const vertices = new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

    const posLoc = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(posLoc);
    gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

    // Cache uniform locations
    uniformsRef.current = {
      u_time: gl.getUniformLocation(program, "u_time"),
      u_speed: gl.getUniformLocation(program, "u_speed"),
      u_turbulence: gl.getUniformLocation(program, "u_turbulence"),
      u_warmth: gl.getUniformLocation(program, "u_warmth"),
      u_brightness: gl.getUniformLocation(program, "u_brightness"),
      u_resolution: gl.getUniformLocation(program, "u_resolution"),
      u_lod: gl.getUniformLocation(program, "u_lod"),
    };
  }, []);

  // Init on mount
  useEffect(() => {
    initGL();
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [initGL]);

  // Resize
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const scale = resolutionScale(displayState);
    const resize = () => {
      canvas.width = Math.round(window.innerWidth * scale);
      canvas.height = Math.round(window.innerHeight * scale);
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
      glRef.current?.viewport(0, 0, canvas.width, canvas.height);
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [displayState]);

  // Render loop
  useEffect(() => {
    const gl = glRef.current;
    const canvas = canvasRef.current;
    if (!gl || !canvas) return;

    const u = uniformsRef.current;
    const fps = targetFPS(displayState);
    const frameInterval = 1000 / fps;
    let lastFrame = 0;

    const render = (now: number) => {
      rafRef.current = requestAnimationFrame(render);

      if (now - lastFrame < frameInterval) return;
      lastFrame = now;

      const elapsed = (now - startTimeRef.current) / 1000;
      gl.uniform1f(u.u_time, elapsed);
      gl.uniform1f(u.u_speed, speed);
      gl.uniform1f(u.u_turbulence, turbulence);
      gl.uniform1f(u.u_warmth, warmth);
      gl.uniform1f(u.u_brightness, brightness);
      gl.uniform2f(u.u_resolution, canvas.width, canvas.height);
      gl.uniform1f(u.u_lod, lodForState(displayState));

      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    };

    rafRef.current = requestAnimationFrame(render);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [speed, turbulence, warmth, brightness, displayState]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full"
      style={{ zIndex: 0 }}
    />
  );
}
