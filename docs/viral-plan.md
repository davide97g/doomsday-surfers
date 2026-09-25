# Viral plan

Goal: every run leaves the phone as something people want to share (a card, a clip, a link, a secret). Nothing here is locked design yet. Each feature goes through the pre-build ritual below and gets Davide's OK before any code.

Written 2026-09-24. Build one feature per session, in order. Tick the status line when a feature ships.

---

## Pre-build ritual (every feature, every session)

1. **Re-check trends.** Slang and meme formats go stale in weeks. Before writing any copy, web-search what's current (TikTok trend roundups, slang glossaries, Know Your Meme). Update the reference bank below with the date.
2. **Ask before building.** Put every doubt and design fork to Davide with `AskUserQuestion`. Each option should name its source: the meme, slang or format it riffs on, where it comes from, and why it lands. For example, "'Aura: −12,400' riffs on *aura farming* (Oxford WotY 2025 shortlist)". No vague "funny copy here". Show the actual lines.
3. **Write the spec into this file** (the feature's section): the final copy, tuning keys, events, files. Then build.
4. **Architecture rules still apply** (CLAUDE.md): `src/sim` stays pure, tuning goes in `tuning.json`, copy goes in `content.json`, the renderer only reads sim state, UI lives in `src/ui` with `data-ui`, and run `bun run typecheck` + `bun run check:gen` after sim changes.

## Viral principles

- **3-second read.** Any 3 s clip of the game must show the pitch without sound: phone world, scrolling, grey = death.
- **Every run produces an artifact.** A card, an emoji line, a clip or a challenge link. There is never a dead end with nothing to post.
- **"This is so me."** Recognition shares best. Diagnoses and stats should feel personal, like horoscopes and Wrapped.
- **Secrets travel.** Hidden endings, easter eggs and "wait, you didn't know?" moments.
- **Escalate to absurd.** Every system has an extreme version. Pick the extreme one unless it breaks tone or perf.
- **Tone guard.** Black Mirror cold, complicit, never preachy. Only the *feed* speaks slang (brands and the algorithm using it slightly wrong is the joke, the "how do you do, fellow kids" energy). The game's narrator voice ("You are present. … Disgusting.") never uses slang. It stays flat and clinical.
- **Legal guard.** Invented brands and handles only. No real people's names or likenesses (not even trending celebrities). No copyrighted audio: riff on meme *formats*, never sample the sound. Never reference Subway Surfers. Mixkit or own footage only.

## Slang and meme reference bank

Verified 2026-09-24. Re-verify before use. The *fit* column is where each could live in the game.

**Evergreen (safe for months or years)**

| term | meaning | fit |
|---|---|---|
| brain rot | Oxford WotY 2024: decay from junk content | diagnosis tier, zone name |
| rage bait | Oxford WotY 2025: content engineered to anger | rename of the Outrage pickup label / Outrage Uncle flavour |
| slop / AI slop | Merriam-Webster WotY 2025 | "Slop zone" (AI-slop visuals), already the SlopCola brand |
| aura, aura farming | coolness points; performing for aura (Oxford 2025 shortlist) | live score popups: "+1000 aura" on loops, "−∞ aura" on crash |
| 6-7 | Dictionary.com WotY 2025, most-searched slang in US | easter egg (see Wildcards) |
| touch grass | go outside, you're too online | already a habit popup; death-card verdict |
| chronically online | lives on the internet | diagnosis tier |
| cooked | doomed, finished | low-battery HUD line: "you're cooked" at <10% |
| delulu | delusional (delulu is the solulu) | diagnosis tier, notification copy |
| NPC / main character | background extra / protagonist energy | diagnosis tiers |
| clanker | insult for AI or robots | the Algorithm boss's nickname in notifications |
| unc | acting old or out of touch | Outrage Uncle's tag, "unc behaviour" diagnosis |
| glazing | over-praising | fake-ad copy, the Algorithm praising you |
| mid | mediocre | rating reels in the feed |
| bed rotting, dopamine menu | wellness-culture words | Wellness Girlie copy |
| POV: / part 2 / wait for it | reel caption formats | already in the bank |
| standing on business | following through | Grindset Bro copy |

**Timely (September 2026, will decay, use in notifications and captions only, never in structural names)**

- *Text From A* (Pretty Little Liars callback): anonymous "-A" texts calling out your embarrassing habits. It fits the push-notification system perfectly, e.g. "I saw you scroll at 3:12 am. Again. -A". Use it as a format, invented copy only.
- *Jimothy the raccoon*: an unbothered raccoon as a mood. The bank already has "this raccoon" in `pools.thing`, so a reel caption riff is cheap.
- *SpongeBob handcuffs*: a serious-looking problem that is trivially escaped. It fits death-screen irony ("You could have just… put it down."). Format only, no character.
- *How could this day get any better*: a reveal that pans to a bigger stash. It fits the Wrapped reveal (one like, then "and 4,212 more").

---

## Build order

| # | feature | why this order | status |
|---|---|---|---|
| 1 | Proof of Doom receipt | cheapest share loop, needed by 2 and 3 | built 2026-09-24, pending on-device share check |
| 2 | Daily Feed + emoji line | reuses card, seed exists | built 2026-09-24, pending on-device check |
| 3 | Ghost challenge links | reuses daily seed, social pull | built 2026-09-24, web hosting pending (name) |
| 4 | Auto-clip highlight montage | video is the real TikTok fuel | built 2026-09-25, pending on-device perf + share check |
| 5 | Hidden ending | the secret, content for 1 and 4 | built 2026-09-25, pending on-device feel check |
| 6 | Set pieces: The Thumb, Algorithm zone, Slop zone, reality intrusions | clip-worthy wow | built 2026-09-25, pending on-device feel + balance check |
| 7 | Pitch-literal scroll gesture (flick combo) | makes the pitch visible in gameplay | built 2026-09-25, pending on-device feel test |
| 8 | Signature audio + first 5 seconds | memeable sound, instant hook | todo |
| 9 | Wildcards (aura, 6-7, -A texts, …) | cheap spice, sprinkle any time | todo |
| — | Work mode (corporate parody, see `docs/work-mode.md`) | niche entry: office humour | built 2026-09-24, pending on-device sound check |

---

## 1. Proof of Doom receipt (built)

**Decided 2026-09-24.**
- Format: a thermal-paper receipt (riffs on Receiptify), "*** FEED MART ***".
- Death screen: the receipt replaces the old Screen Time report. It feeds up out of a printer slot line by line (a tick every other line), then you drag it to read the top (long-receipt energy). Buttons: [PROOF OF DOOM] (paper-white, mono) and [SCROLL AGAIN].
- Items are priced in life costs, drawn at random from a bank per item ("REELS x41 · 3 FRIENDSHIPS", "MUM (IGNORED x3) · PRICELESS").
- Totals: life consumed (1 s = 1 min), aura, attention span, brain age (riffs on Wrapped "Listening Age").
- Then: "TOP x% OF {CRAVING} ADDICTS" (fake percentile, the fake-top-listener meme), diagnosis on the slang ladder NPC → CASUAL SCROLLER → CHRONICALLY ONLINE → COOKED → TERMINALLY ONLINE → POST-HUMAN with one cold line each, and "KILLED BY: A GLASS OF WATER / YOUR MUM / AN AD / A REEL (IT WAS MOVING)".
- Footer: barcode, "THANK YOU FOR YOUR ATTENTION", "NO REFUNDS. NO RETURNS.", "DOOMSDAY SURFERS · #PROOFOFDOOM".
- Share image: 1080×1920. Grey background, the death lines on top, the receipt tilted −1.6°. Share text: "I scrolled {distance} m and was killed by {killer}. #ProofOfDoom".

**Where.**
- `src/ui/receipt.ts`: `buildReceipt` (data), `drawReceipt` (paper canvas + line stops) and `shareCard`.
- `src/ui/share.ts`: `@capacitor/share` + `@capacitor/filesystem` on device, Web Share, or download.
- Copy lives in `content.json` under `report`, numbers in `tuning.json` under `report` (tiers by distance, aura weights, price divisors, brain age, print speed).
- The sim tracks `crashKind` and `lastHabit` for "killed by".
- iOS: `NSPhotoLibraryAddUsageDescription` added so "Save Image" in the share sheet doesn't crash.

**Still to check on device.** Share sheet to Photos, Messages and TikTok; print tick feel; drag on small phones.

**Ideas parked for later.** Daily Feed number in the store line; a secret receipt for the hidden ending ("DIAGNOSIS: PRESENT. DISGUSTING.").

## 2. Daily Feed (built)

**Decided 2026-09-24.**
- **One shot, then locked** (Wordle). The Daily locks the moment its run starts: quitting mid-run shows "Today's Feed #n: abandoned. Coward." Endless runs are always open.
- Day #1 is 2026-09-24 (`tuning.daily.epoch`), with the rollover at local midnight. Each mode has its own seed for the same day, so playing one doesn't spoil the other.
- **Entry point:** the lock-screen notification "⚠️ Time to Doom. ⚠️", riffing on BeReal's daily push.
  - Before playing: "Today's Feed #n is live. 1,464,912 people are scrolling it right now." plus the streak nag, with [SCROLL TODAY'S FEED] and "No thanks, I have a life". Tapping anywhere on the card opens it.
  - After playing: "Today's Feed #n: 1.1 km · killed by 🎞️", "Next feed in 06:00:49" and the old "Day n reward: nothing" gag, with [SHARE RESULT] (text only) and "Claim nothing".
  - The card comes back every time the lock screen does (a nag, on purpose).
- **Share line:** a Wordle grid with one square per 10 s of sim time, colour-coded by average dopamine: 🟩 ≥70, 🟨 ≥45, 🟧 ≥20, 🟥 otherwise. Ten per row, capped at 60, ending in ⬛. Below it: distance, the killer emoji, brain age, top %, "📺 watched an ad to live" if revived, and the hashtag. The death screen's [PROOF OF DOOM] sends it along with the receipt image, and the receipt's store line reads "TODAY'S FEED #n".
- **Streak:** now counts days you played the Daily (shared across modes). Missed days escalate, Duolingo style:
  - 2 days: "not angry, just disappointed"
  - then: "It's fine. It's fine."
  - then: "Your mutuals are asking about you. (They aren't.)"
  - then: "These reminders don't seem to be working. We'll stop sending them for now."
  - then: "Hi. It's us again. We never stopped."
- **Live counter** is parody: it peaks at 3 AM, dips mid-afternoon and wobbles every minute (`tuning.daily.live`).
- **Work mode:** "⚠️ Time for Standup. ⚠️", "Daily Standup #n", "{count} people are on mute in it", "No thanks, I have boundaries", "you left early. Noted.", "📺 watched a webinar to stay online", office killer emoji, and HR-flavoured escalation.

**Where.**
- `src/sim/daily.ts`: day number, seed, time to midnight (pure).
- `World.history`: dopamine samples.
- `src/ui/daily.ts`: local record, grid, share line, live count, countdown.
- `src/ui/title.ts`: the card.
- `main.ts`: `dailyDay`, lock on start, result on each death.
- Copy lives in `content.json` / `content.work.json` under `daily` and `streak.escalation`.
- `check:gen` checks that day numbers step by one (DST included), that seeds don't repeat for 3 years, and that the same Daily seed plays out identically.
- Generator ids are now unique across resets. Resetting the world on the title screen used to reuse ids the renderer was still showing.

**Still to check on device.** The share sheet with text only, how emoji render in Messages and WhatsApp, and the midnight rollover while the lock screen is open.

## 3. Ghost challenge links (built, not hosted yet)

**Decided 2026-09-24.**
- **Build now, host later.** Links use the page's own origin on the web, and `content.share.webUrl` in the native app. That field is empty until the public web build exists, so for now the app's shares leave the link out. Nothing goes public until the name is decided.
- **The receiver plays in the browser** (GeoGuessr-style): same course, your ghost, unlimited retries, no install.
- **Identity:** an auto roast handle ("@hoodie.goblin.4312", from the character at first share). The death screen shows "sharing as @… · rename", and renaming rebuilds the link.
- **Opening a link:** the lock-screen notification becomes "@name challenged you / Beat 687 m of doomscrolling. You won't." with [ACCEPT CHALLENGE] and "No thanks, I'm scared" (decline also clears the link from the URL). If the link is a Daily, it's today's, and you haven't played yet, the race is your Daily ("Their ghost is in today's feed."). A link from the other mode switches mode first.
- **Trash talk** (top-edge pushes from "Challenges"; the handle is always inserted as text, never HTML):
  - "@name ghosted you. Again." when they overtake you after you'd led.
  - "You passed @name. They'll be notified. (They won't.)" when you pass them or their grave.
  - "@name: skill issue 💀" when you die short of their distance.
- **The ghost:** your friend's character as a flickering cyan hologram with a name tag. Where they died it turns into a grey statue with its phone down, tagged "@name was killed by a book here" (Work: "@name logged off here. Cause: …").
- **Receipt:** "YOU MOGGED @NAME / BY 629 M. SCROLLER DIFF." or "@NAME MOGGED YOU / BY 494 M. @NAME DIFF.". The share text leads with "I mogged @name by 629 m 💀" or "@name mogged me by 494 m. Rematch.", then "Beat my scroll: <link>". Every share (endless, Daily and race) carries your own link.

**Tech.**
- `src/sim/ghost.ts`: `GhostRecorder` records positions, not inputs (Math.* can differ between JavaScriptCore and V8). It samples distance, x, y and roll/air flags at 8 Hz of sim time and stores them struct-of-arrays. Distance deltas carry their rounding error forward, so the track never drifts. The header is validated field by field on decode, because links come from strangers.
- `src/ui/ghostLink.ts`: deflate-raw + base64url in `#g=`, so it never reaches a server log.
- `src/ui/race.ts`: pushes, tag and result. `src/ui/handle.ts`: the handle.
- The renderer draws the ghost as its own copy of the hero glb, dressed in one bent MeshBasicMaterial, and projects a head point for the HTML tag.
- `check:gen` round-trips a 169 s bot run: about 1.2 KB in the link, worst error 3 cm.

**Next, when hosting is decided.**
- Deploy the web build and set `share.webUrl`.
- Add universal links (Associated Domains + an AASA file) so the iOS app opens `#g=` links itself; today only the web build reads them.
- Maybe an OG image for link previews in Messages/WhatsApp.

## 4. Auto-clip highlight montage (built)

**Decided 2026-09-25.**
- **Our own editor on WebCodecs, not ReplayKit.** iOS can already screen-record, so our value is the editing. It also means no permission prompt (reported to fire every time on iOS 26), no red recording pill, and it works in the browser too, so ghost-link receivers can post clips. `VideoEncoder` has been on iOS since 16.4, and `AudioEncoder` since iOS 26 (clips are silent before that).
- **Highlight montage, ~15 s:**
  1. Up to 2 highlights, chosen by priority. The gate's 360° orbit comes first, then loops, corkscrews and drops in slow motion (0.7×, with the audio pitched down along with them), ghost overtakes or grave passes, and big air.
  2. The last 5 s into grey.
  3. A 3.2 s end slate: "You are present." "… Disgusting.", the receipt sliding up, then "Beat my scroll · @handle" and "DOOMSDAY SURFERS · #PROOFOFDOOM".
- **Burned in:**
  - A reel-style caption, TikTok's classic white label, picked per run ("WAIT FOR IT", "POV: you said 'one more video' 2 hours ago"; Work: "this meeting could have been an email").
  - Redraws of the notifications and the reel panel's video, plus a redrawn distance and battery.
  - "PART 2 →" after an ad revive.
  - An @handle · game-name watermark.
- **Sharing:** [PROOF OF DOOM] now shares the MP4 and the receipt PNG together, plus the text and link. While the clip is still cutting, the button reads "Rendering your shame…".

**Tech.**
- `src/clip/clip.ts`: `ClipRecorder`. Each render frame is composed into a 540×960 canvas (`compose.ts`), wrapped in a `VideoFrame` and hardware-encoded as H.264 at 60 fps with a keyframe every 0.5 s, into a rolling buffer of about 9 s.
  - Highlight windows are copied out once they finish.
  - The montage is cut with no re-encoding: every segment starts on a keyframe, and slow motion is just longer frame durations. The slate is encoded after the run's frames.
  - Mediabunny (MPL-2.0) muxes the MP4 and is lazy-loaded (~114 KB) only when a clip is cut.
- `src/clip/audio.ts`: a ScriptProcessor tap on the game's master bus, on the same clock as the video.
- Safety valve: if the game drops under `clip.minFps` (52) while running, capture falls to 30 fps for the rest of the session.
- Where WebCodecs is missing, there is simply no clip and the receipt still shares.
- Browser test: a 20.8 s run clip came out at 5.9 MB, 540×960, AAC audio that fades to silence at the grey death.

**Still to check on device.** 60 fps with capture running on an iPhone 14, the share sheet with video + image (Photos, TikTok, Messages), and the audio on iOS 26.

## 5. Hidden ending (built)

**Decided 2026-09-25.** References: The Stanley Parable's waiting endings, WarGames, "Black Mirror" as a literal switched-off screen, and the 2026 dumbphone / go-analog trend.

- **Timeline** (`tuning.ending`, measured in seconds untouched on the final death screen):
  - 30 / 45 / 55 s: escalating lures from "FEED": "Still there? 12 new posts", "We miss you.", "Fine."
  - 60 s: true black, and silence (even the grey room tone cuts).
  - 61 s: "Screen off."
  - 63 s: the reflection, a faceless hooded silhouette in the black glass with a diagonal glare, lit from below by the phone.
  - 68 s: the phone lowers and the glow leaves the face.
  - 70 s: daylight bleeds in (sky gradient, warm rim light) with wind and birds (synth, in `GameAudio.setEnding`).
  - 78 s: "This is the only ending."
  - 85 s: the secret receipt and [PROOF OF DOOM] + [SCROLL AGAIN], greyed out.
  - 95 s: the button unlocks as "scroll again?".
- Any touch or key before the last line cancels back to the plain death screen: the feed wins.
- **Secret receipt:** "STORE CLOSED · AISLE: OUTSIDE", "NOTHING x1 · FREE", "60 SECONDS · YOURS", "DAYLIGHT · INCLUDED", "0 MIN OF LIFE", "AURA · UNMEASURABLE", "BRAIN AGE · YOURS", "TOP 0.4% OF PLAYERS FOUND THIS", "DIAGNOSIS: PRESENT", "KILLED BY: NOTHING", "THANK YOU FOR YOUR INATTENTION", "Don't tell anyone. (Tell everyone.)". It shares as a 9:16 card headed "This is the only ending."
- **Work mode:** "Still there? 12 unread messages", "Your status changed to Away.", "Laptop closed.", "OFFICE CLOSED · FLOOR: OUTSIDE", "DIAGNOSIS: OUT OF OFFICE", "Don't tell HR. (Tell everyone.)", and "clock in again?".
- **Not chosen:** the real-camera reflection, an ending clip, a lock screen that remembers, and the flip-phone character.

**Where.** `src/ui/ending.ts` (overlay, timeline, lures, secret receipt share); `death.ts` owns the idle clock and cancels on touch; `receipt.ts` has `buildSecretReceipt`; `audio.ts` has `setEnding`.

## 6. Set pieces (built)

**Decided 2026-09-25.** References: Shrimp Jesus-style AI slop ("Type YES for 7 years of luck"; no religious imagery), creators keeping the six fingers on purpose, and Threads' "Dear algo" meme.

- **Placement:** one set piece per zone, starting with the zone after the first gate. Every block of three zones plays each of them once, in an order shuffled from the course seed (`src/sim/setpiece.ts`), so the Daily and ghost races see the same ones. The gate's profiling log announces it ("Assigning: THE THUMB"), and the zone card shows "THE THUMB: Your own thumb. Scrolling the world."
- **The Thumb** (Thumb zones, `setPieces.thumb`):
  - Your own colossal thumb comes down from above and behind the camera onto a lane, `lead` s before you reach it. The lane flashes red, and a falling whoosh plays with a light haptic.
  - It lands (slam, shake, heavy haptic) and drags toward you, then lets go. While it's down it counts as a crash: "KILLED BY: YOUR OWN THUMB" 👍.
  - The generator reserves its whole stretch like a moving post, with one lane only and a pickup line in another. `check:gen` verifies that thumbs only spawn in Thumb zones, and the bot dodges them.
- **The Algorithm** (Algorithm zones):
  - A giant eye of feed screens hangs in the sky, fixed to the view and drawn over everything, and follows your lane.
  - While it watches, content gives +50% ("👁 THE ALGORITHM IS WATCHING · +50%" badge, rising sparkle) and pickup runs spawn more often.
  - Hit a habit and it loses interest for 8 s: it squints, looks away, a falling sigh plays, and the badge reads "The algorithm lost interest."
  - Pushes speak "Dear algo" ("Dear algo, show me more", "The algorithm thinks you're special. (It says that to everyone.)").
  - Work: "PERFORMANCE REVIEW", "YOUR MANAGER IS WATCHING".
- **Slop** (Slop zones):
  - The whole feed swaps to a slop atlas: oversaturated dreamy posts with six-fingered glossy hands, engagement-bait captions with typos ("Say NICE if you'd eat this", "Only real ones can count the fingers") and melting drips.
  - Pushes use the slop voice.
  - Work: "WORKSLOP" ("Q3 deck (AI-generated): 14 slides, 0 content").
- **Reality intrusions** (any zone):
  - Below 15% dopamine, over-bright "photos" of real life stand at the track's edge (a sunset, a park bench, a faceless friend waving, a dog whose leash goes up out of frame) with grain and a vignette.
  - A detuned horror sting plays once per dip, and a CSS vignette closes in.

**Where.**
- `src/sim/setpiece.ts`: the schedule.
- `world.ts`: thumb timing and box, `setPiece`, `watching`, `sulkT`.
- `generator.ts`: thumb chunks and the Algorithm's pickup boost.
- `renderer.ts`: `buildThumb`, `buildEye`/`syncEye`, the slop atlas swap in `syncZone`, `syncReality`.
- `textures.ts`: `makeSlopAtlas`, `makeReality`.
- `ui/setpieces.ts`: badge and vignette.
- `ui/gate.ts`: the announcement. `ui/nags.ts`: zone voices.
- `audio.ts`: thumb, algorithm and reality sting. `haptics.ts`: thumb.

**Note.** Generator weights change inside set-piece zones, so courses (and any Daily or ghost links shared before this) differ from zone 1 onward.

## 7. Flick-scroll combo (built)

**Decided 2026-09-25: option A**, the flick combo. The pitch wording stays.
- One swipe up still jumps. A second swipe up within `scroll.window` (0.35 s) is a doomscroll flick, and each further one raises the combo up to ×10.
- Each flick gives:
  - A little dopamine (`scroll.gain` × its own tolerance). The tolerance never recovers and has a 0.03 floor, so spamming runs dry: about 60 dopamine per run in total.
  - A speed burst of +3.5% per combo level, fading over 0.8 s.
- The combo breaks 0.7 s after the last flick.
- Feedback: the "SCROLL SPEED ×N" badge pops (Work: "PING SPEED ×N"), heating from cyan to pink; a tick climbs in pitch; a selection haptic.
- Receipt line: "SCROLLS x87 · 3 THUMB TENDONS" (Work: "SWIPES x87 · 2 CARPAL TUNNELS").

**Where.** `World.flick()` / `combo` / `scrolls` / `scrollTolerance` and `runSpeed`; `tuning.scroll`; the badge lives in `ui/setpieces.ts`.

**To check on device.** Whether rapid thumb flicks feel natural next to jump, and whether 0.35 s is the right window.

## 8. Signature audio + first 5 seconds

- **Voice sting.** A flat, cold "Disgusting." on the death line. It's meme-able as a TikTok sound. The source must be clean: Davide records it, or it is commissioned. Check TTS licences before using any synthesized voice (macOS `say` voices are not cleared for commercial redistribution).
- **Notification ping.** A unique 3-note ping that becomes the game's audio logo, and every share clip ends on it.
- **First launch skips the menu.** The lock screen unlocks straight into a run within 1 s, and character select only appears on the second run. Clips need action in the first second.

**Questions.** Whose voice? Is the menu skip OK for returning players too?

## 9. Wildcards (cheap spice, each needs a yes)

- **Aura score.** Live popups: loop +1000 aura, gate +500, opening a notification +67, crash "−∞ aura". The death card shows the net aura. Rides *aura farming*.
- **6-7 easter egg.** Dying at a distance ending in 67 m, or with exactly 67 pickups, swaps the death line for a special cold one and shows a rare card. People will hunt for it.
- **"-A" texts.** A notification subtype with anonymous callouts of your actual run stats ("You ignored Mum 3 times. -A").
- **Brands speaking slang wrong.** SlopCola: "no cap this cola is bussin fr fr 🧢". The corporate cringe is the joke.
- **"cooked" HUD.** The battery below 10% reads "you're cooked".

---

## Skip list (decided against, with reasons)

- **Real iOS push notifications as parody.** App Store review risk, and it tips from complicit into actually manipulative. Revisit only as strictly opt-in.
- **Reading real Screen Time data.** Needs Apple's Family Controls entitlement, and raw numbers only show inside a DeviceActivityReport extension. Fake it.
- **Real backend leaderboards or percentiles.** Parody numbers are local. No accounts, no backend unless ghosts need a host.

## Sources

- Oxford Word of the Year 2025 (rage bait; shortlist aura farming, biohack): https://corp.oup.com/word-of-the-year/
- Merriam-Webster 2025 (slop): https://www.nbcnews.com/news/amp/rcna247864
- 6-7 most searched US slang: https://www.stvincenttimes.com/6-7-tops-americas-most-searched-slang-words/
- Slang glossaries: https://gabb.com/blog/teen-slang/ · https://en.wikipedia.org/wiki/Glossary_of_2020s_slang · https://www.sheknows.com/parenting/slideshow/1234883077/teen-slang-2026/
- September 2026 TikTok trends: https://newengen.com/insights/september-tiktok-trends/ · https://socialbee.com/blog/trending-tiktok-memes/
- Touch grass / chronically online culture: https://elle.in/trending/gen-z-is-choosing-to-touch-grass-as-the-new-self-care-11879801
