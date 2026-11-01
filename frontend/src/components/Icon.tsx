import type { SVGProps } from "react";

export type IconName =
  | "list" | "table" | "route" | "bars" | "map" | "play" | "pause" | "reset" | "present" | "close" | "prev"
  | "next" | "check" | "plus" | "cube" | "truck" | "split" | "chevron" | "arrow" | "alert" | "spin";

/** One sprite for the whole app (also used by the legacy vis modules' innerHTML snippets). */
export function IconSprite() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true" focusable="false">
      <defs>
    <symbol id="i-list" viewBox="0 0 24 24"><path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.8" cy="6" r="1.1"/><circle cx="4.8" cy="12" r="1.1"/><circle cx="4.8" cy="18" r="1.1"/></symbol>
    <symbol id="i-table" viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="1"/><path d="M3.5 9.5h17M3.5 14.5h17M9.5 4.5v15"/></symbol>
    <symbol id="i-route" viewBox="0 0 24 24"><circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M8 18h5a3 3 0 0 0 0-6h-2a3 3 0 0 1 0-6h5"/></symbol>
    <symbol id="i-bars" viewBox="0 0 24 24"><path d="M5 19V10M12 19V4.5M19 19v-6.5M3 20h18"/></symbol>
    <symbol id="i-map" viewBox="0 0 24 24"><path d="M9 4 3.5 6.5v13.5L9 17.5l6 2.5 5.5-2.5V4L15 6.5 9 4z"/><path d="M9 4v13.5M15 6.5V20"/></symbol>
    <symbol id="i-play" viewBox="0 0 24 24"><path d="M7.5 5v14l11-7z" fill="currentColor"/></symbol>
    <symbol id="i-pause" viewBox="0 0 24 24"><path d="M8.5 5.5v13M15.5 5.5v13" strokeWidth="3"/></symbol>
    <symbol id="i-reset" viewBox="0 0 24 24"><path d="M4.2 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v4.2h4.2"/></symbol>
    <symbol id="i-present" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="1"/><path d="M12 16v4M8 20h8M10.5 7.8v4.4l3.8-2.2z"/></symbol>
    <symbol id="i-close" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></symbol>
    <symbol id="i-prev" viewBox="0 0 24 24"><path d="M14.5 5.5 8 12l6.5 6.5"/></symbol>
    <symbol id="i-next" viewBox="0 0 24 24"><path d="M9.5 5.5 16 12l-6.5 6.5"/></symbol>
    <symbol id="i-check" viewBox="0 0 24 24"><path d="M4.5 12.5l5 5L19.5 7"/></symbol>
    <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
    <symbol id="i-cube" viewBox="0 0 24 24"><path d="M12 3 4 7.5v9L12 21l8-4.5v-9z"/><path d="M4 7.5 12 12l8-4.5M12 12v9"/></symbol>
    <symbol id="i-truck" viewBox="0 0 24 24"><path d="M2.5 6h11v9.5h-11zM13.5 9h4.2l3.3 3.7v2.8h-7.5z"/><circle cx="7" cy="17.6" r="1.9"/><circle cx="17" cy="17.6" r="1.9"/></symbol>
    <symbol id="i-split" viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="7" height="15" rx="1"/><rect x="13.5" y="4.5" width="7" height="15" rx="1"/></symbol>
    <symbol id="i-chevron" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></symbol>
    <symbol id="i-arrow" viewBox="0 0 24 24"><path d="M4.5 12h15M13.5 6l6 6-6 6"/></symbol>
    <symbol id="i-alert" viewBox="0 0 24 24"><path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4.4M12 17.2v.1"/></symbol>
    <symbol id="i-spin" viewBox="0 0 24 24"><path d="M12 3.5a8.5 8.5 0 1 0 8.5 8.5"/></symbol>
  </defs>
    </svg>
  );
}

export function Icon({ name, small = true, className, ...rest }: { name: IconName; small?: boolean; className?: string } & Omit<SVGProps<SVGSVGElement>, "name">) {
  return (
    <svg className={className ?? (small ? "i i-sm" : "i")} aria-hidden="true" {...rest}>
      <use href={`#i-${name}`} />
    </svg>
  );
}
