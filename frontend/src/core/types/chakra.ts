export type ChakraColour =
  | "root"
  | "sacral"
  | "solar"
  | "heart"
  | "throat"
  | "third_eye"
  | "crown";

export interface ChakraPaletteEntry {
  hex: string;
  glow: string;
  gradient: string;
  sanskrit: string;
  label: string;
}

export const CHAKRA_PALETTE: Record<ChakraColour, ChakraPaletteEntry> = {
  root: {
    hex: "#EB5A5A",
    glow: "rgba(235,90,90,0.3)",
    gradient: "linear-gradient(180deg, rgba(235,90,90,0.08) 0%, transparent 60%)",
    sanskrit: "muladhara",
    label: "Root",
  },
  sacral: {
    hex: "#E67E32",
    glow: "rgba(230,126,50,0.3)",
    gradient: "linear-gradient(180deg, rgba(230,126,50,0.08) 0%, transparent 60%)",
    sanskrit: "svadhisthana",
    label: "Sacral",
  },
  solar: {
    hex: "#C9A84C",
    glow: "rgba(201,168,76,0.3)",
    gradient: "linear-gradient(180deg, rgba(201,168,76,0.08) 0%, transparent 60%)",
    sanskrit: "manipura",
    label: "Solar Plexus",
  },
  heart: {
    hex: "#4CB464",
    glow: "rgba(76,180,100,0.3)",
    gradient: "linear-gradient(180deg, rgba(76,180,100,0.08) 0%, transparent 60%)",
    sanskrit: "anahata",
    label: "Heart",
  },
  throat: {
    hex: "#508CDC",
    glow: "rgba(80,140,220,0.3)",
    gradient: "linear-gradient(180deg, rgba(80,140,220,0.08) 0%, transparent 60%)",
    sanskrit: "vishuddha",
    label: "Throat",
  },
  third_eye: {
    hex: "#8C76D7",
    glow: "rgba(140,118,215,0.3)",
    gradient: "linear-gradient(180deg, rgba(140,118,215,0.08) 0%, transparent 60%)",
    sanskrit: "ajna",
    label: "Third Eye",
  },
  crown: {
    hex: "#A05AC8",
    glow: "rgba(160,90,200,0.3)",
    gradient: "linear-gradient(180deg, rgba(160,90,200,0.08) 0%, transparent 60%)",
    sanskrit: "sahasrara",
    label: "Crown",
  },
};
