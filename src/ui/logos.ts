// App logos for the Work mode toasts. With real brands on (dev builds, or
// ?brands=real) they're the real apps' marks; otherwise our parody tiles
// (a generic glyph on the Synergy 365 app colour). Meet and Jira paths are
// from simple-icons (CC0); the others are redrawn from the public marks.

import { realBrands, work } from '../content/content';
import { ICON } from './icons';

export type AppKind = 'chat' | 'sync' | 'call' | 'mail' | 'calendar' | 'ticket' | 'humbl' | 'meeting';

const SLACK = `<svg viewBox="0 0 127 127" aria-hidden="true">
<path fill="#E01E5A" d="M27.2 80c0 7.3-5.9 13.2-13.2 13.2C6.7 93.2.8 87.3.8 80c0-7.3 5.9-13.2 13.2-13.2h13.2V80zm6.6 0c0-7.3 5.9-13.2 13.2-13.2 7.3 0 13.2 5.9 13.2 13.2v33c0 7.3-5.9 13.2-13.2 13.2-7.3 0-13.2-5.9-13.2-13.2V80z"/>
<path fill="#36C5F0" d="M47 27c-7.3 0-13.2-5.9-13.2-13.2C33.8 6.5 39.7.6 47 .6c7.3 0 13.2 5.9 13.2 13.2V27H47zm0 6.7c7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2H13.9C6.6 60.1.7 54.2.7 46.9c0-7.3 5.9-13.2 13.2-13.2H47z"/>
<path fill="#2EB67D" d="M99.9 46.9c0-7.3 5.9-13.2 13.2-13.2 7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2H99.9V46.9zm-6.6 0c0 7.3-5.9 13.2-13.2 13.2-7.3 0-13.2-5.9-13.2-13.2V13.8C66.9 6.5 72.8.6 80.1.6c7.3 0 13.2 5.9 13.2 13.2v33.1z"/>
<path fill="#ECB22E" d="M80.1 99.8c7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2-7.3 0-13.2-5.9-13.2-13.2V99.8h13.2zm0-6.6c-7.3 0-13.2-5.9-13.2-13.2 0-7.3 5.9-13.2 13.2-13.2h33.1c7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2H80.1z"/>
</svg>`;

const TEAMS = `<svg viewBox="0 0 24 24" aria-hidden="true">
<circle cx="18" cy="6.2" r="2.4" fill="#5059C9"/><rect x="14.6" y="9.4" width="8.4" height="8.8" rx="2.6" fill="#5059C9"/>
<circle cx="11.6" cy="5" r="3.3" fill="#7B83EB"/><rect x="6.4" y="9.4" width="10.6" height="11.2" rx="3" fill="#7B83EB"/>
<rect x="1" y="6.4" width="12" height="12" rx="1.6" fill="#4B53BC"/>
<rect x="3.9" y="9" width="6.2" height="1.8" fill="#fff"/><rect x="6.1" y="9" width="1.8" height="7" fill="#fff"/>
</svg>`;

const OUTLOOK = `<svg viewBox="0 0 24 24" aria-hidden="true">
<rect x="8.5" y="3.5" width="14.5" height="17" rx="1.6" fill="#28A8EA"/>
<path fill="#0364B8" d="M8.5 11.5 15.75 16 23 11.5V19a1.5 1.5 0 0 1-1.5 1.5h-11.5A1.5 1.5 0 0 1 8.5 19z"/>
<path fill="#14447D" opacity=".35" d="M8.5 11.5 15.75 16 23 11.5"/>
<rect x="1" y="6" width="12" height="12" rx="1.6" fill="#0F6CBD"/>
<ellipse cx="7" cy="12" rx="2.7" ry="3.3" fill="none" stroke="#fff" stroke-width="1.8"/>
</svg>`;

const LINKEDIN = `<svg viewBox="0 0 24 24" aria-hidden="true">
<rect width="24" height="24" rx="4" fill="#0A66C2"/>
<circle cx="6.4" cy="6.6" r="1.6" fill="#fff"/><rect x="5" y="9.5" width="2.8" height="9" fill="#fff"/>
<path fill="#fff" d="M10 9.5h2.7v1.3c.5-.9 1.7-1.6 3.1-1.6 2.5 0 3.2 1.6 3.2 4.1v5.2h-2.8v-4.6c0-1.2-.2-2.1-1.5-2.1-1.4 0-1.9 1-1.9 2.2v4.5H10z"/>
</svg>`;

const MEET = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#00897B" d="M5.53 2.13 0 7.75h5.53zm.398 0v5.62h7.608v3.65l5.47-4.45c-.014-1.22.031-2.25-.025-3.46-.148-1.09-1.287-1.470-2.236-1.36zM23.1 4.32c-.802.295-1.358.995-2.047 1.49-2.506 2.05-4.982 4.12-7.468 6.19 3.025 2.59 6.04 5.18 9.065 7.760 1.218.671 1.428-.814 1.328-1.64v-13a.828.828 0 0 0-.877-.825zM.038 8.15v7.7h5.53v-7.7zm13.577 8.1H6.008v5.62c3.864-.006 7.737.011 11.58-.009 1.02-.07 1.618-1.12 1.468-2.07v-2.51l-5.47-4.68v3.65zm-13.577 0c.02 1.44-.041 2.88.033 4.31.162.948 1.158 1.43 2.047 1.310h3.464v-5.62z"/></svg>`;

const JIRA = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#0052CC" d="M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005zm5.723-5.756H5.736a5.215 5.215 0 0 0 5.215 5.214h2.129v2.058a5.218 5.218 0 0 0 5.215 5.214V6.758a1.001 1.001 0 0 0-1.001-1.001zM23.013 0H11.455a5.215 5.215 0 0 0 5.215 5.215h2.129v2.057A5.215 5.215 0 0 0 24 12.483V1.005A1.001 1.001 0 0 0 23.013 0Z"/></svg>`;

const REAL: Record<AppKind, string> = {
  chat: SLACK,
  sync: TEAMS,
  call: TEAMS,
  mail: OUTLOOK,
  calendar: OUTLOOK,
  ticket: JIRA,
  humbl: LINKEDIN,
  meeting: MEET,
};

// Parody: Synergy 365 app colour + a generic glyph.
const PARODY: Record<AppKind, [string, string]> = {
  chat: ['#d9486c', ICON.chat],
  sync: ['#2bb5a4', ICON.chat],
  call: ['#2bb5a4', ICON.call],
  mail: ['#3b82f6', ICON.mail],
  calendar: ['#f59e0b', ICON.event],
  ticket: ['#ef4444', ICON.check],
  humbl: ['#8b5cf6', ICON.person],
  meeting: ['#2bb5a4', ICON.video],
};

/** The app's logo, sized by the parent (`.logo` fills its box). */
export function appLogo(kind: AppKind): string {
  if (realBrands) return `<span class="logo">${REAL[kind]}</span>`;
  const [bg, glyph] = PARODY[kind];
  return `<span class="logo parody" style="--app:${bg}">${glyph}</span>`;
}

/** The app's display name: the real one with real brands on, else Synergy 365's. */
export function appName(kind: AppKind): string {
  if (realBrands) return work.real.apps[kind];
  const cards = work.cards;
  return kind === 'meeting' ? cards.call.app : cards[kind].app;
}
