export const TYPES = {
  metric: { label: "Metrics", singular: "Metric" },
  process: { label: "Processes", singular: "Process" },
  practice: { label: "Practices", singular: "Practice" },
  skill: { label: "Skills", singular: "Skill" },
  experience: { label: "Experiences", singular: "Experience" },
  training: { label: "Trainings", singular: "Training" },
  aptitude: { label: "Aptitudes", singular: "Aptitude" },
};

export const ATTRIBUTES = [
  { code: "RL", name: "Reliability", focus: "Customer" },
  { code: "RS", name: "Responsiveness", focus: "Customer" },
  { code: "AG", name: "Agility", focus: "Customer" },
  { code: "CO", name: "Cost", focus: "Internal" },
  { code: "AM", name: "Asset Management Efficiency", focus: "Internal" },
  { code: "GS", name: "GreenSCOR", focus: "Special application" },
];

export const CATEGORIES = [
  { code: "sP", name: "Plan" },
  { code: "sS", name: "Source" },
  { code: "sM", name: "Make" },
  { code: "sD", name: "Deliver" },
  { code: "sR", name: "Return" },
  { code: "sE", name: "Enable" },
];

export const PRACTICE_TYPES = ["Emerging", "Best", "Standard"];

// The section files the original PDF was split into, by SCOR section number
export const PDF_SECTIONS = {
  "1.1": "Performance: Reliability",
  "1.2": "Performance: Responsiveness",
  "1.3": "Performance: Agility",
  "1.4": "Performance: Cost",
  "1.5": "Performance: Asset Management Efficiency",
  "2.1": "Processes: Plan",
  "2.2": "Processes: Source",
  "2.3": "Processes: Make",
  "2.4": "Processes: Deliver",
  "2.5": "Processes: Deliver / Return",
  "2.6": "Processes: Enable",
  "3.1": "Practices: Emerging",
  "3.2": "Practices: Best",
  "3.3": "Practices: Standard",
  "4.1": "People: Skills",
  "5.1": "Special Applications: GreenSCOR",
};

export function subtitle(e) {
  if (e.type === "metric") return `${e.attribute} · Level ${e.level}`;
  if (e.type === "process") return `${e.category} · Level ${e.level}`;
  if (e.type === "practice") return `${e.practiceType ?? ""} practice`.trim();
  return TYPES[e.type]?.singular ?? e.type;
}
