/**
 * Theme palettes for mode-driven visual switching.
 *
 * R&D mode  → Gruvbox Hard Dark (warm, textured, energetic)
 * Research  → Solarized Dark (cool, clinical, precise)
 *
 * Keys match Tailwind CSS custom property names from @theme in index.css.
 * The ThemeProvider sets these on document.documentElement to override
 * the build-time @theme values at runtime.
 */

export type ThemePalette = Record<string, string>;

export const GRUVBOX_DARK: ThemePalette = {
  // Neutral scale (zinc)
  "zinc-950": "#1d2021",
  "zinc-900": "#282828",
  "zinc-800": "#3c3836",
  "zinc-700": "#504945",
  "zinc-600": "#665c54",
  "zinc-500": "#928374",
  "zinc-400": "#bdae93",
  "zinc-300": "#d5c4a1",
  "zinc-200": "#ebdbb2",
  "zinc-100": "#fbf1c7",
  "zinc-50": "#fdf4c9",

  // Green (success)
  "green-300": "#b8bb26",
  "green-400": "#b8bb26",
  "green-500": "#98971a",
  "green-600": "#79740e",

  // Red (error)
  "red-300": "#fb4934",
  "red-400": "#fb4934",
  "red-500": "#cc241d",
  "red-600": "#9d0006",

  // Yellow (warning)
  "yellow-300": "#fabd2f",
  "yellow-400": "#fabd2f",
  "yellow-500": "#d79921",
  "yellow-600": "#b57614",

  // Blue (info)
  "blue-300": "#83a598",
  "blue-400": "#83a598",
  "blue-500": "#458588",
  "blue-600": "#076678",

  // Orange (action)
  "orange-300": "#fe8019",
  "orange-400": "#fe8019",
  "orange-500": "#d65d0e",
  "orange-600": "#af3a03",

  // Fuchsia/purple (special)
  "fuchsia-300": "#d3869b",
  "fuchsia-400": "#d3869b",
  "fuchsia-500": "#b16286",
  "fuchsia-600": "#8f3f71",

  // Emerald/aqua (accent)
  "emerald-300": "#8ec07c",
  "emerald-400": "#8ec07c",
  "emerald-500": "#689d6a",
  "emerald-600": "#427b58",

  // Cyan/aqua
  "cyan-300": "#8ec07c",
  "cyan-400": "#8ec07c",
  "cyan-500": "#689d6a",
  "cyan-600": "#427b58",

  // Amber (used in animations)
  "amber-400": "#fabd2f",

  // Semantic aliases (design language §3.1)
  bg: "#1d2021",
  surface: "#282828",
  elevated: "#3c3836",
  border: "#504945",
  "border-muted": "#665c54",
  "text-muted": "#928374",
  "text-secondary": "#bdae93",
  "text-primary": "#ebdbb2",
  "text-emphasis": "#fbf1c7",
  "text-bright": "#fdf4c9",
};

export const SOLARIZED_DARK: ThemePalette = {
  // Neutral scale — Solarized base colors mapped to zinc slots
  "zinc-950": "#002b36", // base03 — main background
  "zinc-900": "#073642", // base02 — card/panel background
  "zinc-800": "#0a4050", // interpolated — interactive elements
  "zinc-700": "#2f525b", // interpolated — borders
  "zinc-600": "#436068", // interpolated — muted borders
  "zinc-500": "#586e75", // base01 — secondary text
  "zinc-400": "#657b83", // base00 — labels
  "zinc-300": "#839496", // base0 — body text
  "zinc-200": "#93a1a1", // base1 — primary text
  "zinc-100": "#eee8d5", // base2 — emphasis
  "zinc-50": "#fdf6e3",  // base3 — brightest

  // Green (success)
  "green-300": "#859900",
  "green-400": "#859900",
  "green-500": "#6b7a00",
  "green-600": "#4e5c00",

  // Red (error)
  "red-300": "#dc322f",
  "red-400": "#dc322f",
  "red-500": "#b5201e",
  "red-600": "#8e100e",

  // Yellow (warning)
  "yellow-300": "#b58900",
  "yellow-400": "#b58900",
  "yellow-500": "#946f00",
  "yellow-600": "#735600",

  // Blue (info / primary accent in Solarized)
  "blue-300": "#268bd2",
  "blue-400": "#268bd2",
  "blue-500": "#1a6da8",
  "blue-600": "#0e507e",

  // Orange (action)
  "orange-300": "#cb4b16",
  "orange-400": "#cb4b16",
  "orange-500": "#a33c11",
  "orange-600": "#7b2d0d",

  // Fuchsia → magenta
  "fuchsia-300": "#d33682",
  "fuchsia-400": "#d33682",
  "fuchsia-500": "#ab2a69",
  "fuchsia-600": "#831f50",

  // Emerald → cyan
  "emerald-300": "#2aa198",
  "emerald-400": "#2aa198",
  "emerald-500": "#21817a",
  "emerald-600": "#19615c",

  // Cyan → violet
  "cyan-300": "#6c71c4",
  "cyan-400": "#6c71c4",
  "cyan-500": "#565a9e",
  "cyan-600": "#404378",

  // Amber → Solarized yellow (used in animations)
  "amber-400": "#b58900",

  // Semantic aliases (design language §3.1)
  bg: "#002b36",
  surface: "#073642",
  elevated: "#0a4050",
  border: "#2f525b",
  "border-muted": "#436068",
  "text-muted": "#586e75",
  "text-secondary": "#657b83",
  "text-primary": "#839496",
  "text-emphasis": "#93a1a1",
  "text-bright": "#fdf6e3",
};

/** Semantic color helpers for components that need hex values directly. */
export interface SemanticColors {
  success: string;
  error: string;
  warning: string;
  info: string;
  accent: string;
  muted: string;
  text: string;
  bg: string;
  surface: string;
}

export function semanticColors(palette: ThemePalette): SemanticColors {
  return {
    success: palette["green-400"],
    error: palette["red-400"],
    warning: palette["yellow-400"],
    info: palette["blue-400"],
    accent: palette["orange-400"],
    muted: palette["zinc-500"],
    text: palette["zinc-200"],
    bg: palette["zinc-950"],
    surface: palette["zinc-900"],
  };
}
