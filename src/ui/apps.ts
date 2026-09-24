// Work mode app windows for the desk (desk.ts). Opening a card docks the app it
// came from, and the app keeps living: Slack fills with messages and unread
// badges, Teams chat trades bubbles, Outlook's inbox and calendar keep
// stacking up, the Jira ticket bounces between statuses and gathers comments,
// the LinkedIn feed grows. Every few seconds (work.windows.tickMin..tickMax)
// something new lands. Branding comes from logos.ts (real in dev builds).

import { work } from '../content/content';
import { fill, pick } from '../content/templates';
import { TUNING } from '../sim/types';
import { appLogo, appName } from './logos';
import { hue, initials, MeetWindow, type AppWindow } from './meeting';

const W = TUNING.work.windows;
const A = work.apps;
const C = work.cards;
const CHAT_LINES = [...C.chat.lines, ...C.sync.lines];

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function clock(offsetMin = 0): string {
  const d = new Date(Date.now() - offsetMin * 60000);
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function avatar(name: string, cls = 'av'): string {
  return `<i class="${cls}" style="--h:${hue(name)}">${initials(name)}</i>`;
}

function short(name: string): string {
  return name.replace(/\s*\(.*\)/, '');
}

/** Keep a list short: the oldest rows fall off. */
function cap(list: HTMLElement, max: number, fromTop: boolean): void {
  while (list.children.length > max) (fromTop ? list.lastElementChild : list.firstElementChild)?.remove();
}

function el(html: string): HTMLElement {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild as HTMLElement;
}

abstract class Ticking implements AppWindow {
  readonly el: HTMLElement;
  private tickIn = rand(W.tickMin, W.tickMax);

  constructor(cls: string, html: string) {
    this.el = document.createElement('div');
    this.el.className = `win ${cls}`;
    this.el.innerHTML = html;
  }

  update(dt: number): void {
    this.tickIn -= dt;
    if (this.tickIn > 0) return;
    this.tickIn = rand(W.tickMin, W.tickMax);
    this.tick();
  }

  protected abstract tick(): void;
}

/** Slack: workspace sidebar with unread channels, a live channel. */
class SlackWindow extends Ticking {
  private readonly msgs: HTMLElement;
  private readonly unread = new Map<string, number>();

  constructor(from: string, text: string) {
    const ch = pick(A.chat.channels);
    super(
      'app-slack',
      `<aside class="sk-side">
        <div class="sk-ws">${A.chat.workspace}</div>
        ${A.chat.channels.map((c) => `<div class="sk-ch${c === ch ? ' on' : ''}" data-c="${c}"># ${c}<i></i></div>`).join('')}
      </aside>
      <div class="sk-main">
        <div class="sk-head">${appLogo('chat')}<b># ${ch}</b></div>
        <div class="sk-msgs"></div>
        <div class="sk-input">${fill(A.chat.input, { channel: ch })}</div>
      </div>`,
    );
    this.msgs = this.el.querySelector('.sk-msgs')!;
    const l = pick(CHAT_LINES);
    this.add(fill(l.from), fill(l.text), 7);
    this.add(from, text, 0);
  }

  protected tick(): void {
    if (Math.random() < 0.55) {
      const l = pick(CHAT_LINES);
      this.add(fill(l.from), fill(l.text), 0);
      return;
    }
    // Somewhere else is on fire too.
    const others = [...this.el.querySelectorAll<HTMLElement>('.sk-ch:not(.on)')];
    const c = pick(others);
    const n = (this.unread.get(c.dataset.c!) ?? 0) + 1 + Math.floor(Math.random() * 3);
    this.unread.set(c.dataset.c!, n);
    c.classList.add('unread');
    c.querySelector('i')!.textContent = String(n);
  }

  private add(from: string, text: string, ago: number): void {
    const m = el(`<div class="sk-msg">${avatar(from, 'sq')}<div><b></b><span>${clock(ago)}</span><p></p></div></div>`);
    m.querySelector('b')!.textContent = short(from);
    m.querySelector('p')!.textContent = text;
    this.msgs.append(m);
    cap(this.msgs, 5, false);
  }
}

/** Teams chat: left rail, one conversation, their bubbles and your "ok"s. */
class TeamsWindow extends Ticking {
  private readonly msgs: HTMLElement;

  constructor(private readonly from: string, text: string) {
    super(
      'app-teams',
      `<aside class="tm-rail">${appLogo('sync')}<i></i><i class="on"></i><i></i><i></i></aside>
      <div class="tm-main">
        <div class="tm-head">${avatar(from)}<b></b><span>Chat</span></div>
        <div class="tm-msgs"></div>
        <div class="tm-input">${A.sync.input}</div>
      </div>`,
    );
    this.el.querySelector('.tm-head b')!.textContent = short(from);
    this.msgs = this.el.querySelector('.tm-msgs')!;
    this.add(text, false);
  }

  protected tick(): void {
    if (Math.random() < 0.3) this.add(pick(A.sync.mine), true);
    else this.add(fill(pick(C.sync.lines).text), false);
  }

  private add(text: string, mine: boolean): void {
    const m = el(`<div class="tm-msg${mine ? ' mine' : ''}"><span>${mine ? '' : `${short(this.from)} · `}${clock()}</span><p></p></div>`);
    m.querySelector('p')!.textContent = text;
    this.msgs.append(m);
    cap(this.msgs, 5, false);
  }
}

/** Outlook inbox: new mail keeps landing on top, the unread count climbs. */
class OutlookWindow extends Ticking {
  private readonly list: HTMLElement;
  private readonly count: HTMLElement;
  private unread = 11 + Math.floor(Math.random() * 30);

  constructor(from: string, subject: string) {
    super(
      'app-outlook',
      `<div class="ol-bar">${appLogo('mail')}<b>${appName('mail')}</b><span class="ol-search">${A.mail.search}</span></div>
      <div class="ol-title"><b>Inbox</b><span class="ol-count"></span></div>
      <div class="ol-tabs"><span class="on">${A.mail.tabs[0]}</span><span>${A.mail.tabs[1]}</span></div>
      <div class="ol-list"></div>`,
    );
    this.list = this.el.querySelector('.ol-list')!;
    this.count = this.el.querySelector('.ol-count')!;
    const l = pick(C.mail.lines);
    this.add(fill(l.from), fill(l.text), 12, false);
    this.add(from, subject, 0, true);
  }

  protected tick(): void {
    const l = pick(C.mail.lines);
    this.add(fill(l.from), fill(l.text), 0, true);
  }

  private add(from: string, subject: string, ago: number, unread: boolean): void {
    if (unread) this.unread++;
    this.count.textContent = String(this.unread);
    const m = el(`<div class="ol-row${unread ? ' unread' : ''}">${avatar(from)}<div><div class="ol-top"><b></b><span>${clock(ago)}</span></div><div class="ol-subj"></div><div class="ol-prev"></div></div></div>`);
    m.querySelector('b')!.textContent = from;
    m.querySelector('.ol-subj')!.textContent = subject;
    m.querySelector('.ol-prev')!.textContent = pick(C.mail.preview);
    this.list.prepend(m);
    cap(this.list, 5, true);
  }
}

/** Outlook calendar: Calendar Tetris, one more meeting every few seconds. */
class CalendarWindow extends Ticking {
  private readonly grid: HTMLElement;
  private blocks = 0;

  constructor(from: string, title: string) {
    const hours = A.calendar.hours;
    super(
      'app-cal',
      `<div class="ol-bar">${appLogo('calendar')}<b>${appName('calendar')}</b><span class="ol-search">${A.calendar.title}</span></div>
      <div class="cal-grid">${hours.map((h, i) => `<span class="cal-h" style="top:${(i / hours.length) * 100}%">${h}</span>`).join('')}</div>`,
    );
    this.grid = this.el.querySelector('.cal-grid')!;
    this.add(pick(work.meeting.titles), 1);
    this.add(title, 3, from);
  }

  protected tick(): void {
    this.add(Math.random() < 0.5 ? pick(work.meeting.titles) : fill(pick(C.calendar.lines).text), Math.floor(Math.random() * A.calendar.hours.length));
  }

  private add(title: string, hour: number, who = ''): void {
    const n = A.calendar.hours.length;
    const len = Math.random() < 0.4 ? 2 : 1;
    const lane = this.blocks % 3;
    this.blocks++;
    const b = el(`<div class="cal-ev" style="--c:${hue(title) % 360};top:${(hour / n) * 100}%;height:${(Math.min(len, n - hour) / n) * 100}%;left:calc(18px + ${lane * 18}%)"><b></b><span></span></div>`);
    b.querySelector('b')!.textContent = title;
    b.querySelector('span')!.textContent = who ? short(who) : '';
    this.grid.append(b);
    // Keep the day readable-ish: drop the oldest blocks.
    const evs = this.grid.querySelectorAll('.cal-ev');
    if (evs.length > 9) evs[0].remove();
  }
}

/** Jira: one ticket that never closes. */
class JiraWindow extends Ticking {
  private readonly status: HTMLElement;
  private readonly points: HTMLElement;
  private readonly comments: HTMLElement;
  private sp = 3;
  private st = 0;

  constructor(from: string, text: string) {
    const key = text.match(/TKT-\d+/)?.[0] ?? `TKT-${1000 + Math.floor(Math.random() * 9000)}`;
    const quoted = text.match(/"([^"]+)"/)?.[1];
    const J = A.ticket;
    super(
      'app-jira',
      `<div class="jr-bar">${appLogo('ticket')}<b>${appName('ticket')}</b></div>
      <div class="jr-crumb">Projects / ${J.project} / ${key}</div>
      <div class="jr-title"></div>
      <div class="jr-status"></div>
      <div class="jr-fields">
        <span>${J.fields[0]}</span><b>${avatar('You Me')}You</b>
        <span>${J.fields[1]}</span><b class="jr-prio">${J.priority}</b>
        <span>${J.fields[2]}</span><b class="jr-sp"></b>
        <span>${J.fields[3]}</span><b>${J.sprint}</b>
      </div>
      <div class="jr-comments"></div>`,
    );
    this.el.querySelector('.jr-title')!.textContent = quoted && !quoted.startsWith('@') ? quoted : pick(J.titles);
    this.status = this.el.querySelector('.jr-status')!;
    this.points = this.el.querySelector('.jr-sp')!;
    this.comments = this.el.querySelector('.jr-comments')!;
    this.setStatus(1);
    this.points.textContent = String(this.sp);
    this.comment(from, pick(J.comments));
  }

  protected tick(): void {
    const r = Math.random();
    if (r < 0.4) {
      let s = Math.floor(Math.random() * A.ticket.statuses.length);
      if (s === this.st) s = (s + 1) % A.ticket.statuses.length;
      this.setStatus(s);
    } else if (r < 0.85) this.comment(fill(Math.random() < 0.5 ? '{boss}' : '{coworker}'), pick(A.ticket.comments));
    else {
      this.sp += 5;
      this.points.textContent = String(this.sp);
    }
  }

  private setStatus(s: number): void {
    this.st = s;
    const name = A.ticket.statuses[s];
    this.status.textContent = name;
    this.status.dataset.s = name.split(' ')[0].toLowerCase();
  }

  private comment(who: string, text: string): void {
    const m = el(`<div class="jr-c">${avatar(who)}<div><b></b><span> ${clock()}</span><p></p></div></div>`);
    m.querySelector('b')!.textContent = short(who);
    m.querySelector('p')!.textContent = text;
    this.comments.prepend(m);
    cap(this.comments, 3, true);
  }
}

/** LinkedIn: the feed. Posts pile up, reactions only go up. */
class LinkedInWindow extends Ticking {
  private readonly feed: HTMLElement;
  private readonly counts: { el: HTMLElement; n: number }[] = [];

  constructor(from: string, text: string) {
    super(
      'app-li',
      `<div class="li-bar">${appLogo('humbl')}<span class="li-search">Search</span></div>
      <div class="li-feed"></div>`,
    );
    this.feed = this.el.querySelector('.li-feed')!;
    this.post(fill('{coworker}'), pick(A.humbl.posts));
    this.post(from, text);
  }

  protected tick(): void {
    if (Math.random() < 0.4) this.post(fill(Math.random() < 0.5 ? '{coworker}' : '{handle}'), pick(A.humbl.posts));
    for (const c of this.counts) {
      c.n += 3 + Math.floor(Math.random() * 90);
      c.el.textContent = c.n.toLocaleString('en-US');
    }
  }

  private post(who: string, text: string): void {
    const p = el(`<div class="li-post">
      <div class="li-who">${avatar(who)}<div><b></b><span> ${A.humbl.degree}</span><small>${Math.ceil(Math.random() * 23)}h · 🌐</small></div></div>
      <p></p>
      <div class="li-react"><span class="li-emo">👍❤️👏</span><span class="li-n">0</span></div>
      <div class="li-acts">${A.humbl.actions.map((a) => `<span>${a}</span>`).join('')}</div>
    </div>`);
    p.querySelector('b')!.textContent = short(who);
    p.querySelector('p')!.textContent = text.startsWith('is ') || text.startsWith('endorsed') ? `${short(who)} ${text}` : text;
    const n = { el: p.querySelector<HTMLElement>('.li-n')!, n: 12 + Math.floor(Math.random() * 400) };
    n.el.textContent = n.n.toLocaleString('en-US');
    this.counts.unshift(n);
    if (this.counts.length > 3) this.counts.pop();
    this.feed.prepend(p);
    cap(this.feed, 3, true);
  }
}

/** The window an opened card docks: `kind` is the card kind (or 'call'). */
export function makeWindow(kind: string, who: string, text: string): AppWindow {
  switch (kind) {
    case 'call':
      return new MeetWindow(who);
    case 'chat':
      return new SlackWindow(who, text);
    case 'sync':
      return new TeamsWindow(who, text);
    case 'mail':
      return new OutlookWindow(who, text);
    case 'calendar':
      return new CalendarWindow(who, text);
    case 'ticket':
      return new JiraWindow(who, text);
    default:
      return new LinkedInWindow(who, text);
  }
}
