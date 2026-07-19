// Small inline SVG icons (Lucide-style). The skill's checklist: SVG, never emoji.
const base = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" };

export const Film = (p) => (
  <svg width={p.size || 18} height={p.size || 18} viewBox="0 0 24 24" {...base} strokeWidth={1.7}>
    <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" />
  </svg>
);
export const Clock = (p) => (
  <svg width={p.size || 12} height={p.size || 12} viewBox="0 0 24 24" {...base}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
);
export const Users = (p) => (
  <svg width={p.size || 12} height={p.size || 12} viewBox="0 0 24 24" {...base}><circle cx="12" cy="8" r="3.5" /><path d="M5 20c0-3.3 3.1-5 7-5s7 1.7 7 5" /></svg>
);
export const Eye = (p) => (
  <svg width={p.size || 14} height={p.size || 14} viewBox="0 0 24 24" {...base}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" /></svg>
);
export const Trash = (p) => (
  <svg width={p.size || 14} height={p.size || 14} viewBox="0 0 24 24" {...base}><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" /></svg>
);
export const List = (p) => (
  <svg width={p.size || 16} height={p.size || 16} viewBox="0 0 24 24" {...base}><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></svg>
);
export const Settings = (p) => (
  <svg width={p.size || 16} height={p.size || 16} viewBox="0 0 24 24" {...base}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);
export const Download = (p) => (
  <svg width={p.size || 13} height={p.size || 13} viewBox="0 0 24 24" {...base}><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 21h16" /></svg>
);
export const X = (p) => (
  <svg width={p.size || 15} height={p.size || 15} viewBox="0 0 24 24" {...base}><path d="M18 6 6 18M6 6l12 12" /></svg>
);
export const Check = (p) => (
  <svg width={p.size || 13} height={p.size || 13} viewBox="0 0 24 24" {...base}><path d="M20 6 9 17l-5-5" /></svg>
);
export const AlertTriangle = (p) => (
  <svg width={p.size || 13} height={p.size || 13} viewBox="0 0 24 24" {...base}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01" /></svg>
);
export const DownloadCloud = (p) => (
  <svg width={p.size || 18} height={p.size || 18} viewBox="0 0 24 24" {...base}><path d="M8 17l4 4 4-4M12 12v9" /><path d="M20.9 18.4A5 5 0 0 0 18 9h-1.3A8 8 0 1 0 4 16.3" /></svg>
);
