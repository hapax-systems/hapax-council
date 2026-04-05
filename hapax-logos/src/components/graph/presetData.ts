/**
 * Preset categories with reference material.
 * 10 aesthetic categories, each with presets and 4 exemplary works.
 */

export interface ReferenceWork {
  artist: string;
  title: string;
  year: string;
  description: string;
}

export interface PresetCategory {
  id: string;
  label: string;
  presets: string[];
  references: ReferenceWork[];
}

export const PRESET_CATEGORIES: PresetCategory[] = [
  {
    id: "minimal",
    label: "Minimal / Transparent",
    presets: ["ambient"],
    references: [
      { artist: "Andy Warhol", title: "Screen Tests", year: "1964-66", description: "472 silent portrait films, single unbroken takes." },
      { artist: "James Benning", title: "13 Lakes", year: "2004", description: "Thirteen 10-minute static shots, pure observational cinema." },
      { artist: "Bill Viola", title: "The Reflecting Pool", year: "1977-79", description: "Radical clarity of the unprocessed frame." },
      { artist: "Michael Snow", title: "Wavelength", year: "1967", description: "45-minute zoom foregrounding perception itself." },
    ],
  },
  {
    id: "temporal",
    label: "Temporal Persistence / Feedback",
    presets: ["ghost", "trails", "feedback_preset"],
    references: [
      { artist: "Nam June Paik", title: "TV Buddha", year: "1974", description: "Foundational video feedback loop as art." },
      { artist: "Steina & Woody Vasulka", title: "Noisefields", year: "1974", description: "Audio-video feedback experiments at The Kitchen." },
      { artist: "Zbigniew Rybczynski", title: "Tango", year: "1980", description: "36 temporal layers coexisting in one room." },
      { artist: "Paul Sharits", title: "N:O:T:H:I:N:G", year: "1968", description: "Polychromatic flicker creating temporal persistence." },
    ],
  },
  {
    id: "analog",
    label: "Analog Degradation",
    presets: ["vhs_preset", "dither_retro", "nightvision"],
    references: [
      { artist: "Pipilotti Rist", title: "I'm Not The Girl Who Misses Much", year: "1986", description: "Deliberate VHS degradation as ritual." },
      { artist: "Greig Fraser / Kathryn Bigelow", title: "Zero Dark Thirty (raid)", year: "2012", description: "Authentic night-vision device on ARRI Alexa." },
      { artist: "Rosa Menkman", title: "A Vernacular of File Formats", year: "2010", description: "Systematic codec failure aesthetics." },
      { artist: "JODI", title: "%20Wrong", year: "1999", description: "Digital degradation as native artistic vocabulary." },
    ],
  },
  {
    id: "glitch",
    label: "Databending / Glitch",
    presets: ["datamosh", "datamosh_heavy", "glitch_blocks_preset", "pixsort_preset"],
    references: [
      { artist: "Takeshi Murata", title: "Monster Movie", year: "2005", description: "Datamoshed B-movie, now at Smithsonian." },
      { artist: "Kanye West / Nabil Elderkin", title: "Welcome to Heartbreak", year: "2009", description: "Datamoshing enters mainstream hip hop." },
      { artist: "Kim Asendorf", title: "Mountain Tour", year: "2010", description: "Invented the pixel sorting algorithm." },
      { artist: "Chairlift / Ray Tintori", title: "Evident Utensil", year: "2009", description: "Choreographed datamoshing as visual instrument." },
    ],
  },
  {
    id: "syrup",
    label: "Houston Syrup / Hip Hop Temporal",
    presets: ["screwed", "trap"],
    references: [
      { artist: "DJ Screw", title: "Screw Tapes", year: "1991-2000", description: "300+ mixtapes defining the source aesthetic." },
      { artist: "A$AP Rocky / Dexter Navy", title: "L$D", year: "2015", description: "Liquefied psychedelic smears through Tokyo neon." },
      { artist: "Travis Scott / Dave Meyers", title: "SICKO MODE", year: "2018", description: "Purple-hued desaturation and frame stuttering." },
      { artist: "Gaspar Noe", title: "Enter the Void", year: "2009", description: "Foundational cinematic psychedelic temporal distortion." },
    ],
  },
  {
    id: "spectral",
    label: "False Color / Spectral",
    presets: ["neon", "thermal_preset"],
    references: [
      { artist: "Richard Mosse", title: "The Enclave", year: "2013", description: "Kodak Aerochrome infrared film in eastern Congo." },
      { artist: "Dan Flavin", title: "untitled (Wheeling Peachblow)", year: "1966-68", description: "Fluorescent light sculptures as spectral saturation." },
      { artist: "Gaspar Noe / Tom Kan", title: "Enter the Void (titles)", year: "2009", description: "Neon spectrum strobing typography." },
      { artist: "Ryoji Ikeda", title: "test pattern", year: "2008-ongoing", description: "Data streams remapped to spectral gradients." },
    ],
  },
  {
    id: "edge",
    label: "Edge / Silhouette / Relief",
    presets: ["silhouette", "sculpture"],
    references: [
      { artist: "Saul Bass", title: "The Man with the Golden Arm (titles)", year: "1955", description: "Silhouette as narrative device in motion graphics." },
      { artist: "Richard Linklater", title: "A Scanner Darkly", year: "2006", description: "Interpolated rotoscope as shifting edge detection." },
      { artist: "Daniel Rozin", title: "Wooden Mirror", year: "1999", description: "Live camera feed converted to physical relief sculpture." },
      { artist: "Saul Bass / John Whitney", title: "Vertigo (titles)", year: "1958", description: "Computational image processing meets graphic design." },
    ],
  },
  {
    id: "mosaic",
    label: "Halftone / Mosaic / Character",
    presets: ["halftone_preset", "ascii_preset"],
    references: [
      { artist: "Knowlton & Harmon", title: "Studies in Perception I", year: "1966", description: "Foundational computer mosaic from Bell Labs." },
      { artist: "Ryoji Ikeda", title: "datamatics", year: "2006-ongoing", description: "Pure data as black-and-white visual grid." },
      { artist: "Jim Campbell", title: "Portrait of My Father", year: "2000", description: "16x24 LED grid portrait." },
      { artist: "Vuk Cosic", title: "ASCII History of Moving Images", year: "1998", description: "Lumiere and Psycho as ASCII streams." },
    ],
  },
  {
    id: "geometric",
    label: "Geometric Distortion / Symmetry",
    presets: ["fisheye_pulse", "kaleidodream", "mirror_rorschach", "tunnelvision", "voronoi_crystal"],
    references: [
      { artist: "Hype Williams / Missy Elliott", title: "The Rain (Supa Dupa Fly)", year: "1997", description: "Fisheye lens as hip hop visual identity." },
      { artist: "James Whitney", title: "Lapis", year: "1966", description: "Analog computer mandala animation." },
      { artist: "Douglas Trumbull", title: "2001: A Space Odyssey (Stargate)", year: "1968", description: "Slit-scan tunnel via mechanical apparatus." },
      { artist: "Jordan Belson", title: "Allures", year: "1961", description: "30 simultaneous projectors at the Vortex Concerts." },
    ],
  },
  {
    id: "reactive",
    label: "Biometric / Reactive",
    presets: ["heartbeat", "diff_preset", "slitscan_preset"],
    references: [
      { artist: "Rafael Lozano-Hemmer", title: "Pulse Room", year: "2006", description: "Incandescent bulbs pulsing with visitor heartbeats." },
      { artist: "Daniel Rozin", title: "Mechanical Mirrors series", year: "1999-ongoing", description: "Frame differencing driving physical actuators." },
      { artist: "Douglas Trumbull", title: "slit-scan rig for 2001", year: "1968", description: "Original temporal-spatial scanning apparatus." },
      { artist: "Sabato Visconti", title: "Glitch Landscapes", year: "2012-ongoing", description: "Corrupted camera firmware at moment of capture." },
    ],
  },
];
