/** Per-source filters that can be independently applied to Live or Trail layers. */

export interface SourceFilter {
  name: string;
  css: string;
}

export const SOURCE_FILTERS: SourceFilter[] = [
  { name: "None", css: "none" },
  // Color shifts
  { name: "Cyan", css: "sepia(1) saturate(5) hue-rotate(160deg) brightness(0.7) contrast(1.3)" },
  { name: "Amber", css: "sepia(1) saturate(3) hue-rotate(-10deg) brightness(0.75) contrast(1.2)" },
  { name: "Violet", css: "sepia(1) saturate(4) hue-rotate(230deg) brightness(0.65) contrast(1.3)" },
  { name: "Rose", css: "sepia(1) saturate(4) hue-rotate(310deg) brightness(0.7) contrast(1.2)" },
  { name: "Lime", css: "sepia(1) saturate(5) hue-rotate(70deg) brightness(0.7) contrast(1.2)" },
  { name: "Orange", css: "sepia(1) saturate(4) hue-rotate(10deg) brightness(0.75) contrast(1.3)" },
  // Tonal
  { name: "Mono", css: "grayscale(1) brightness(1.3) contrast(1.4)" },
  { name: "Sepia", css: "sepia(0.8) contrast(1.1) brightness(0.9)" },
  { name: "Bleach", css: "saturate(0.3) contrast(1.6) brightness(1.1)" },
  { name: "Crush", css: "saturate(0) contrast(3) brightness(1.2)" },
  // Texture
  { name: "Soft", css: "blur(1.5px) brightness(1.1)" },
  { name: "Sharp", css: "contrast(1.5) saturate(1.3) brightness(0.95)" },
  { name: "Blown", css: "contrast(1.8) brightness(1.3) saturate(1.5)" },
  // Psychedelic
  { name: "Invert", css: "invert(1) hue-rotate(180deg)" },
  { name: "Thermal", css: "sepia(1) saturate(6) hue-rotate(-30deg) brightness(0.6) contrast(1.8)" },
  { name: "Acid", css: "saturate(4) hue-rotate(90deg) contrast(1.4) brightness(0.8)" },
  { name: "Neon", css: "saturate(5) contrast(1.5) brightness(1.2)" },
  { name: "X-Ray", css: "invert(0.85) grayscale(1) contrast(2) brightness(1.3)" },
];
