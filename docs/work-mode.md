# Work mode (corporate parody)

Built 2026-09-24. Aimed at the corporate-humour niche: Slack/Teams pings, email, meetings, spreadsheets, decks. It's a separate mode on the same sim. The title lock screen has a Focus pill ("Personal" / "Work"); tapping it saves the choice and restarts the app in the other mode.

## Real brands vs parody

The toasts copy the real layouts: the macOS banner (Slack, Jira, LinkedIn pushes), the Teams chat toast with its quick-reply box, the Teams incoming call (video and audio accept, red hang-up), the Windows 11 Outlook mail and calendar toasts, and the Meet call grid. `realBrands` (`src/content/content.ts`) decides the branding:
- **Dev builds** (`bun run dev`) or `?brands=real`: real names (`work.real` in content.work.json), real logos (`src/ui/logos.ts`: Meet and Jira from simple-icons (CC0), the rest redrawn), real colours, Segoe UI/SF/Roboto fonts. For local fun only.
- **Production builds** (TestFlight) or `?brands=parody`: the same layouts under the Synergy 365 parody names, with glyph tiles as logos.
- Testing: `game.nags.demo('call' | 'chat' | 'sync' | 'mail' | 'calendar' | 'ticket' | 'humbl')` shows one card now.

## Legal rule (the reason it looks the way it does)

- **No real app sounds, names, logos or UI.** Slack's knock and the Teams ringtone are copyrighted recordings, and the app names, logos and popup designs are trademarks and trade dress. App Review rejects them (guideline 5.2).
- **Sound-alikes only:** community sounds from Freesound and Pixabay in the same style (`public/assets/sfx/`, CREDITS.md): a CC0 knock for chat, CC0 message pops for the Teams-style chat and mail, Universfield's marimba ringtone from Pixabay (Pixabay Content License) for calls, and a CC-BY hang-up for Decline. Calendar, ticket and Humbl use synth sounds from `src/audio/audio.ts`, which also stands in for any sample that hasn't loaded yet. Rips of the real app sounds (Zedge, Voicy, archive.org packs) are off-limits.
- **Popups echo the layout** (app header, square avatar, bold sender, `#channel`, Accept/Decline) with our own colours and glyphs.
- **Invented suite "Synergy 365"**: Huddle (chat), Sync (calls), Inbox (mail), Calendar, Tickets, Humbl (the social network). Coworker names are generic first names with a department.

## How it works

- `src/content/content.ts` picks the mode (`?mode=work|personal`, else `localStorage['ds.mode']`) and lays `src/config/content.work.json` over `content.json`: objects merge, arrays replace. Work-only copy lives under the `work` key.
- **The sim is untouched.** Work renames what each slot means:

| slot | Personal | Work |
|---|---|---|
| content 0–3 | Likes, Notifications, Reels, Outrage | Reactions, Pings, Meetings, Reply-alls |
| habits 0–3 | water, book, shoes, Mum | Lunch break (lunch box), PTO request, Gym at 6, Home calling |
| thrills | loop, corkscrew, drop, air | PIVOT, REORG, BUDGET CUT, PROMOTION (TITLE ONLY) |
| meter | dopamine battery | presence pill: Available ≥ `work.status.awayBelow`, Away ≥ `brbBelow`, Be right back, Offline |
| death | "You are present. … Disgusting." | "You logged off. … Unprofessional." [CLOCK IN AGAIN] |
| receipt | Proof of Doom, FEED MART | Proof of Work, SYNERGY 365 |

- **Cards** (`src/ui/nags.ts`): chat, mail, calendar, ticket and Humbl cards, weighted by `work.cards.*.weight`. With chance `ui.callChance` (one at a time) a card is an incoming call instead. It rings until it's gone (it also stops while the run is paused) and stays up for `ui.callShow` s. Accept or a tap opens the meeting panel, and Decline shows a guilt toast.
- **The desk** (`src/ui/desk.ts`, `src/ui/apps.ts`, `src/ui/meeting.ts`): opening a card docks its app in a side column (slots in the order top-left, top-right, bottom-left, bottom-right, all inside the top 60%). The apps:
  - call: Meet window (initial-avatar tiles, captions, control bar); several calls can run at once
  - chat: Slack (aubergine sidebar, unread badges, live channel)
  - sync: Teams chat (bubbles, your "ok"s)
  - mail: Outlook inbox (new mail on top, unread count)
  - calendar: Outlook day view (Calendar Tetris)
  - ticket: Jira ticket (status keeps changing, comments, story points only go up)
  - humbl: LinkedIn feed (posts, reactions only go up)

  Something new lands every `work.windows.tickMin..tickMax` s. Windows ignore pointers, never close on their own and can't be closed. A checkpoint gate or the end of the run clears the desk, and the oldest window is replaced when all `work.windows.max` slots are full.
- **Trickle**: the UI reports the window count (`world.setOpenWindows`). Each open window adds `work.windows.trickle` dopamine/s × `windowTolerance`, which drops by `toleranceDecay` (floor `toleranceFloor`) with every window opened (`world.windowOpened`).
- **World** (`src/render/textures.ts`, the Work section): the track and towers are spreadsheets, slides, Calendar Tetris days and mail threads. Reels are `.pptx` decks and low barriers are mail slabs.
- **Music** becomes elevator hold music (96 BPM, maj7 chords). It still follows dopamine.
- **Cast**: Middle Manager (shirt, tie, lanyard, mug; craves Meetings), Remote Worker (hoodie, pyjama bottoms, slippers, headset, mouse jiggler; craves Pings), LinkedIn Lunatic (blazer, selfie stick, green "open to work" ring; craves Reactions). They are tuning indices 7–9, entries with `"mode": "work"` in `content.characters`, and built by `runner.py --character manager|remote|linkedin`.

## Next

- Intern, Scrum Master, Corporate Girlie (Stanley cup).
- On-device: ear-check the ring and knock (the feel should be recognisable, but they must not be the real melody), 60 fps in the office world, and the reload flash on the Focus toggle.

## Trend refs (verified 2026-09-24)

Workslop, quiet cracking, coffee badging, FOBO (fear of AI taking your job). Evergreen: "per my last email", "you're on mute", "this could have been an email", "circle back", "hard stop", Calendar Tetris, the yellow "Away" dread and mouse jigglers, LinkedIn "humbled to announce… Agree?".
Sources: https://testlify.com/top-hr-buzzwords/ · https://www.icaew.com/students/student-insights/2026-office-jargon-and-how-to-avoid-it
