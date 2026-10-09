# Web launch + Instagram (2026-10-09)

## Decisions

- **Name: Scrollcoaster**, subtitle "Don't Stop Scrolling". Research on 2026-10-09 found .com, .gg, .app, .game and .lol unregistered, and no game with the name on the App Store, Steam or itch. "Doom" stays out of the title because ZeniMax forced DoomRL to rename. #PROOFOFDOOM as a hashtag is fine.
- **Hosting:** Cloudflare Pages (free, unlimited bandwidth) at `https://scrollcoaster.com/`.
- **Instagram:** a series on Davide's existing YouTube-channel account, [@ai_quack](https://www.instagram.com/ai_quack/), not a new game account. The link in the bio points at the game.
- **Today's Feed #1 = launch day.** Reset `tuning.daily.epoch` when the launch date is set.
- **In-app browsers:** the death screen nudges people out of Instagram, Facebook and TikTok's in-app browsers. Credits are fine print on the receipt.

## Done in the repo

- Production builds compile out the real-brand Work mode (no `?brands=real`). The bundle carries no Slack/Teams/... logos, only the unused name strings in `content.work.json`.
- `public/credits.html` (served at `/credits`) carries the CC BY credit for the decline sound, plus the other sources and open-source licences. Every receipt prints "CREDITS: SCROLLCOASTER.COM/CREDITS".
- `index.html` has the title, description and Open Graph/Twitter tags with `og.jpg` (1200×630, a loop frame plus the name). It also links the icons and `manifest.webmanifest`.
- `public/_headers`:
  - Hashed bundles live in `build/` and are cached as immutable.
  - Models, clips and sounds are cached for a day, then revalidated.
- First visit is 7 MB, down from 13. The title no longer preloads the next biome (that waits until the run starts) or the select screen's neighbours (they load once you flick).
- Every user-facing string is renamed: lock screen, receipt, clip watermark, iOS display name.
- The bundle id is now `com.davideghiotto.scrollcoaster`; no App Store record existed yet. The old "Doomsday Surfers" app on the iPhone is a separate app now, so delete it by hand.
- `content.share.webUrl` is set, so native-app shares carry real links.
- `bun run deploy:web` builds the site and uploads it to the Pages project `scrollcoaster`.

## Davide's steps, in order

1. **Domain.** Buy `scrollcoaster.com` (Cloudflare Registrar sells at cost). Optionally buy `.gg`/`.app` too and redirect them, so nobody squats them once it spreads.
2. **Instagram handle.** Check by hand that @scrollcoaster is free (the research couldn't see past the login wall). Grab it even though posts go out from the channel account: it stops impersonators, and it can redirect to the channel.
3. **Cloudflare.** Sign in and create the project:
   ```
   ! bunx wrangler login
   ! bunx wrangler pages project create scrollcoaster --production-branch main
   ```
4. **Daily epoch.** Set `tuning.daily.epoch` to the launch date, then run `bun run check:gen`.
5. **Deploy.** Run `bun run deploy:web`. In the dashboard, go to Pages → scrollcoaster → Custom domains, add `scrollcoaster.com`, then `www`, redirected to the apex.
6. **Device pass** (below), then post.

Optional: connect the GitHub repo in Pages for auto-deploys from `main` (build `bun run build`, output `dist`, env `BUN_VERSION`). Cloudflare Web Analytics is cookie-free. If you turn it on, change the "no tracking" line in `credits.html`.

## Device pass before posting

| where | check |
|---|---|
| iPhone Safari | 60 fps or the Auto tier steps down; audio after the first tap; the clip and the receipt share; the Daily grid share |
| Instagram in-app browser, iOS | game runs; the nudge appears and its link opens Safari (needs iOS 17+) |
| Instagram in-app browser, Android | game runs; the nudge opens Chrome |
| Android Chrome | game runs; clip and receipt share |
| desktop Chrome/Safari | keyboard controls work; a `#g=` ghost link opens the race |
| link previews | Messages, WhatsApp, Instagram DM, plus [opengraph.xyz](https://www.opengraph.xyz) and Meta's Sharing Debugger |
| `/credits` | opens, and its back link returns to the game |

## Instagram series plan

- **Bio:** one cold line plus the link, for example "Don't stop scrolling. ↓ scrollcoaster.com".
- **Reels** are the game's own PROOF OF DOOM clips, which are already 9:16 with caption, montage and watermark. Post them as they come out of the game; the burned-in caption is the hook. Cross-post to YouTube Shorts.
- **Stories:**
  - Today's Feed: the emoji grid, with a link sticker to the site.
  - Ghost challenges: "beat my scroll" with your `#g=` link.
- **Pinned:** a gameplay trailer reel (the loop, a gate scan, death into grey), a tease of the hidden ending (don't show it, just "there's another ending"), and one dev-log reel.
- **Cadence for launch week:** one Reel a day, plus a daily Story for Today's Feed.
- **Copy:** follow the pre-build ritual in `docs/viral-plan.md`. Re-check slang and trends on the day you write captions, and keep the narrator voice flat.
- **Never:**
  - Record clips for posting from a dev build: Work mode shows the real Slack/Teams logos there. Use the deployed site or a production build.
  - Use Subway Surfers hashtags or split-screen bait.

## Later

- Run a USPTO/EUIPO trademark search for "Scrollcoaster" (classes 9 and 41) before the App Store.
- Universal links (Associated Domains + AASA on scrollcoaster.com), so the iOS app opens `#g=` links.
- Measure the first visit on mobile data in the Instagram in-app browser. If it's slow, consider a lighter first character.
