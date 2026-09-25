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
| 4 | Auto-clip (last 8 s) | video is the real TikTok fuel | todo |
| 5 | Hidden ending | the secret, content for 1 and 4 | todo |
| 6 | Set pieces: The Thumb, Algorithm zone, Slop zone, reality intrusions | clip-worthy wow | todo |
| 7 | Pitch-literal scroll gesture | makes the pitch visible in gameplay | todo (needs decision) |
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

## 4. Auto-clip (last 8 seconds)

**Hook.** The loop, the gate orbit and the crash into grey reality become a ready-made vertical video. This is the actual TikTok fuel.

**Extreme version.**
- Auto-save the last 8 s on death, plus special "wow" clips (loop, corkscrew, gate scan, big air), each with a burned-in caption from the reel caption bank ("POV: you have 4 min of battery", "WAIT FOR IT").
- End slate: the death copy, then the game name.
- "Part 2 →" if the run revived.

**Tech and risks.**
- **HTML overlays are not in the WebGL canvas.** `canvas.captureStream` would miss notifications, the death text and the HUD, which are the funniest parts. So:
- **Preferred on iOS: ReplayKit clip buffering.** `RPScreenRecorder.shared().startClipBuffering()` + `exportClip(to:duration:)` (iOS 15+) keeps a rolling buffer and exports the last N seconds of the whole screen *including HTML and app audio*. It needs a small custom Capacitor plugin in Swift (`ios/App/…`). Check whether iOS shows a recording indicator or prompt and whether that's acceptable.
- Web fallback: MediaRecorder on a composite canvas (WebGL frame + a 2D redraw of the key overlays). It's more work. Could ship iOS-only first.
- Perf gate: iPhone 14 must hold 60 fps while buffering. Measure before and after.
- Share via the `@capacitor/share` flow from feature 1.

**Questions.**
- iOS-only first?
- Which moments auto-clip, and is it opt-in or on by default?
- Include audio?

## 5. Hidden ending (60 s idle on the death screen)

**Hook.** The secret people tell friends about ("stay on the death screen, don't touch anything"). It is also the most Black Mirror beat in the game.

**Draft script** (each beat on a timer, any touch cancels back to the normal death screen):
- 0–60 s: the normal death screen. The report sits there. At 30 s a notification tries to lure you back ("Still there? {number} new posts"). At 45 s: "We miss you." At 55 s: "Fine."
- 60 s: the screen fades to true black and all audio cuts. Text, barely visible: "Screen off."
- 63 s: in the black a faint reflection appears, the faceless runner's silhouette looking at the viewer: the black mirror, literal.
- 68 s: the runner slowly lowers their phone. Its glow leaves their face. For the first time the face is lit by something else: warm daylight colour bleeds in, the real sky, wind and birds (no music).
- 78 s: one line, flat: "This is the only ending."
- 85 s: [SCROLL AGAIN] fades back in, greyed out, and stays disabled for 10 s. Its label slowly changes to [scroll again?].
- Afterwards: an achievement-style notification on the next launch: "You found the ending. Don't tell anyone. (Tell everyone.)". This unlocks a secret card for feature 1 ("Diagnosis: Present. Disgusting.").

**Extreme option (needs decision).** At 63 s, instead of the silhouette, show the **player's real face** through the front camera, darkened and desaturated like a reflection in an off screen. Maximum wow. Cost: the camera permission prompt breaks the surprise unless the prompt itself is the joke. It could be asked earlier with the purpose string "Doomsday Surfers wants to see you." Needs `NSCameraUsageDescription`, must never record or upload, and App Review may question it.

**Questions.**
- Silhouette or real camera?
- Does finding the ending change anything permanently (a new title-screen state, a "grey" character skin)?
- Should the runner's face be revealed (breaks "faceless") or stay faceless and turn toward the light?

## 6. Set pieces

All clip bait. Each is a zone or event in the course generator, obstacle rules unchanged (gates on flat straights, no falling deaths).

- **The Thumb.** A colossal human thumb comes out of the sky and swipes down the track like it's scrolling the world. It crushes one lane at a time, telegraphed by a lane-wide glow and a haptic tick. Your own gesture is the monster. It is readable in any clip without sound.
- **Algorithm zone ("the clanker").** A huge eye/feed made of stacked screens chases you. It shouts glazing notifications ("you're literally so valid for this", "king behaviour") while spawning denser content. A boss-lite chase with no new death rule; it ends at the next gate.
- **Slop zone.** AI-slop visuals: six-fingered hands as posts, melting text, morphing reels, captions with slightly wrong grammar. It rides the Merriam-Webster 2025 word and "clanker" discourse.
- **Reality intrusions near zero dopamine.** Below ~15%, near-photoreal fragments fade into the grey (a park bench, a friend waving, a sunset, a dog wanting a walk), treated as horror (a sting sound, a vignette). Must stay procedural or free-licensed, and cheap on perf.
- **Infinite-scroll drop as a literal feed.** On vertical drops the track becomes a wall of giant posts, and likes burst as you pass.

**Questions.** Which one first? Does The Thumb crushing count as a barrier crash (instant zero) or a big dopamine hit?

## 7. Pitch-literal scroll gesture (decision needed)

**Problem.** The pitch is "you die if you stop doomscrolling", but dopamine never drains on its own, so stopping is safe. A viewer never sees the pitch happen.

**Options.**
- A. **Flick-scroll combo.** Rapid repeated short swipe-ups (the real scroll motion) give a small speed/dopamine tick with its own tolerance, and the HUD shows "SCROLL SPEED ×3". Conflict: swipe-up is jump. It could use a two-finger flick or "repeated micro-flicks within 150 ms". Needs a feel test.
- B. **Idle = the feed pauses the run** with a "keep going?" style guilt prompt (already a comedy element) that escalates. No drain, but stopping is visibly punished.
- C. **Reword the pitch** to match the mechanic ("An endless runner where healthy habits kill you").

**Questions.** Pick A, B or C.

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
