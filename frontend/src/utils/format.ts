export const humanize = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const bytes = (n: number) => {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
};

export const timeAgo = (iso: string) => {
  const d = new Date(iso);
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return d.toLocaleDateString();
};

export const pad2 = (n: number) => String(n).padStart(2, "0");

export const LAYOUT_LABELS: Record<string, string> = {
  cover: "Cover", section_divider: "Section divider", executive_summary: "Executive summary", two_column: "Two columns",
  three_column: "Three columns", text_image: "Text + visual", image_text: "Visual + text", process: "Process",
  timeline: "Timeline", architecture: "Architecture", workflow: "Workflow", comparison: "Comparison", kpi: "KPI cards",
  chart: "Chart", table: "Table", research_methodology: "Methodology", research_results: "Results", key_findings: "Key findings",
  quote: "Quote", conclusion: "Conclusion", references: "Sources",
};
