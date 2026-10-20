# Proposal: a Grok-native Workroom

Status: proposal, not implemented. Research date: 2026-10-19.
Mockup: [`mockup.html`](mockup.html) (open it directly in a browser, the button at the top right switches the theme).

| Light | Dark |
|---|---|
| ![Mockup, light](screenshots/mockup-light.png) | ![Mockup, dark](screenshots/mockup-dark.png) |

Phone width (390px, dark): [`screenshots/mockup-mobile-dark.png`](screenshots/mockup-mobile-dark.png).

## 1. The Grok look, in one paragraph

Grok and Grok Bot use a near-monochrome, warm-neutral UI. The light background is an off-white with a slight warm cast (`#f9f8f7`), dark mode is a warm near-black (`#131211`), and the ink is near-pure black or white (`#050505` / `#fcfcfc`). Chrome is almost colorless. Primary actions are solid ink pills: black on light, white on dark. Secondary actions are borderless or hairline pills. Shapes are generous: pills (`9999px`) for every button and chip, 24px for cards and the composer, 16px for chat bubbles, 10px for list rows. There are no shadows; depth comes from a 4–6% tint. Type is a neutral grotesk (`universalSans`, then Inter) at 14–15px, with headings at weight 550 and slight negative tracking. Color is kept for meaning. Each Bot gets a saturated round avatar (teal, orange, purple, blue, red) with two eyes. Amber marks "your turn". Teal marks a Bot-to-Bot handoff ("Asking Research…"). A red dot marks unread. A blue ring marks keyboard focus. The voice is that of a capable colleague: Bot status lines are lowercase, terse and outcome-first ("sent. inbox at zero, 5 drafts parked for tomorrow."), and humans stay in control ("held for your ok", "come back when your approval is needed").

## 2. Research: what is verified and what is inferred

Measured on 2026-10-19 with Playwright `getComputedStyle` on the live pages. "Verified" means the value was read off the page. "Inferred" means it was estimated from screenshots or derived by us.

### Verified (with source)

| Fact | Value | Source |
|---|---|---|
| grok.com page background, light | `rgb(249,248,247)` = `#f9f8f7` | https://grok.com (body) |
| grok.com page background, dark | `rgb(19,18,17)` = `#131211` | https://grok.com, `prefers-color-scheme: dark` |
| grok.com ink | `#050505` light / `#fcfcfc` dark | https://grok.com body color |
| grok.com secondary text | `#636363` light / `#9e9e9e` dark | https://grok.com toolbar buttons |
| grok.com composer surface | `#ffffff`, 1px `#e6e5e3`, radius 24px (light); `#201f1d`, 1px `rgba(252,252,252,.06)`, radius 24px (dark) | https://grok.com `.query-bar` |
| grok.com font stack | `universalSans, Inter, Roboto, "Open Sans", Arial, sans-serif, ui-sans-serif, system-ui` | https://grok.com |
| grok.com sizes | body 15px; buttons 14px/500, letter-spacing -0.2px; h1 24px/550, letter-spacing -0.48px; textarea 16px | https://grok.com |
| Buttons are pills | radius `9999px`; primary = ink background (`#050505` / `#fcfcfc`), secondary = 1px `rgba(15,13,10,.08)` hairline | https://grok.com "Sign up" / "Sign in" |
| Focus ring color | `rgba(56,87,199,.5)` in the composer ring shadow | https://grok.com `.query-bar` box-shadow |
| Motion | `color, background-color, border-color 0.1s cubic-bezier(0.4,0,0.2,1)` | https://grok.com buttons |
| Icons | outline, `stroke="currentColor"`, `stroke-width: 1.75`, 16px (`size-4`) | https://grok.com toolbar SVG |
| x.ai marketing type | `xVf` (proprietary variable font), weights 400/450/500; Geist Mono for code; h1 60px/450, -0.6px | https://x.ai |
| x.ai marketing surfaces | white page; cards `#f9f8f6` (also `rgba(16,16,0,.04)`) with radius 24px; pills `9999px` | https://x.ai, https://x.ai/bot |
| Grok Bot app mock (on the product page) | `system-ui` 16px; Bot list rows radius 10px, selected `rgba(10,10,10,.055)`; timestamps `rgba(20,20,20,.4)` 12px; previews `rgba(20,20,20,.6)` 12px; human initials avatar 28px circle, `rgba(10,10,10,.055)`, 10px/500 | https://x.ai/bot hero |
| "Your turn" chip | text `rgb(178,106,0)` on `rgba(178,106,0,.14)`, radius 999px, 12px ("You're in control") | https://x.ai/bot "Grok Bot works where you work" |
| Handoff chip | text `rgb(0,147,163)` on `#f2feff`, pill, with animated dots ("Asking Research…", "Looping in Comms…", "Sending to Chief…") | https://x.ai/bot "Connect the Bots" |
| Unread badge | 10.5px `rgb(255,59,48)` dot on the avatar | https://x.ai/bot hero |
| Chat bubbles | Bot bubble `rgba(16,16,0,.04)` radius 16px, padding 8px 12px; the user's own message is a dark ink bubble | https://x.ai/bot |
| Product framing | "AI teammates you can give real work to." "come back when your approval is needed", "keep working 24/7", "Put a few Bots in the same thread and they pass work between themselves." | https://x.ai/bot |
| Bot naming | "Bot" capitalized; Bots are named by role ("Chief", "Inbox Manager", "Talent Scout"); "Each Team Bot has its own handle" | https://x.ai/bot, https://x.ai/news/team-bots |
| Group chat and mentions | "Use a group when several Bots need one shared outcome and visible handoffs." "Type `@` and select a Bot when one teammate owns the request." | https://docs.x.ai/grok-bot/chat-and-collaboration |
| Creation verb | "Create new Bot" (not "spawn" or "hire") in the docs; the marketing mock shows "Spawning" | https://docs.x.ai/grok-bot/bots, https://x.ai/bot |
| Approvals vocabulary | "Ask first" rules; sensitive actions "can stop for approval" | https://docs.x.ai/grok-bot/faq |
| Brand rules | Don't "use our Marks in any app title, domain name, or the name of any product or service not made or provided by us", or in any way that could "imply our endorsement"; use logos only unaltered | https://x.ai/legal/brand-guidelines (dated February 14, 2025) |

### Inferred (not read from a computed style)

- Bot avatar palette (teal `#4fb8a8`, orange `#f5a03a`, purple `#7c5cf5`, blue `#3b82f6`, coral `#f0643c`, red `#e8453c`): sampled by eye from the x.ai/bot hero screenshot. The real avatars are artwork, not CSS.
- Dark-mode variants of the amber, teal, success and danger colors: the dark x.ai/bot page was not measured. We lightened the light values to reach WCAG AA on `#131211`.
- Success green: neither Grok surface uses a status green that we found. `#1f8a4c` / `#5fd08a` are our choice, kept low-saturation so they don't compete with the avatars.
- "Needs attention" vs "Unread activity" sidebar grouping: a search snippet attributed this to the Grok Bot docs, but we could not load that page (404), so it is unverified. The mockup's "Needs you" group borrows the idea.
- Press screenshots of the Grok Bot desktop app (October 2026) were not available to us beyond the product-page mock. The app mock on x.ai/bot is the closest primary source.

## 3. Where the current Workroom diverges

Read from `dashboard/public/index.html`, `assets/style.css` and `assets/app.js` at `2ee8d8f`.

| Area | Workroom today | Grok |
|---|---|---|
| Palette | Sage green tint everywhere (`--bg:#f9faf7`, `--ink:#222c23`, `--green` accent, green focus outline) | Warm neutral, ink-only accents, blue focus |
| Type | DM Sans, 10–12px for most UI text (`.meta`, `.pill`, `.field-note`, `.nav-count` = 10px) | Inter-class grotesk at 14–15px; 12px is the floor (timestamps) |
| Eyebrows | `.eyebrow`: 10px uppercase, letter-spacing 1px | Sentence-case group labels in tertiary ink, no caps |
| Radii | 4–9px (`.button` 6px, `.pill` 5px, `.panel` 9px) | Pills, 24px cards, 16px bubbles, 10px rows |
| Buttons | Rectangular, hairline border | Pill; primary = solid ink |
| Panels | Bordered `.panel` boxes, with a shadow on the active nav item and on the dialog | Flat tinted cards, no shadow |
| Avatars | Olive and khaki blob (`.bot-avatar` tones `#424f41`, `#927044`, `#577366`) | Saturated, distinct hue per Bot |
| Messages | Rows divided by rules (`.message` border-bottom); mention = green `mark` | Bubbles; mention = teal text; own messages in an ink bubble |
| Tabs | Underline tabs (`.tabs button` border-bottom) | Segmented pill control |
| Sidebar | Generic nav ("Network", "Project work") with glyph icons (◌ ⊞ ▱) | The sidebar is the Bot/thread inbox: avatar, name, last line, time |
| Status | "Connecting" text with an amber dot | Small dot plus a word; "working" uses animated dots |
| Copy | Careful and procedural ("Connection perspective · not a sign-in", "Delivered means the webhook accepted the request…") | Short, outcome-first, human-in-control |

## 4. Design tokens

Paste into `:root` in `style.css`. The theme switch follows the same pattern as the mockup: light by default, dark under `@media (prefers-color-scheme: dark)` scoped to `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`. (The current file uses `light-dark()`; either works. If you keep `light-dark()`, use each row as `light-dark(<light>, <dark>)`.)

| Token | Light | Dark | Source / justification |
|---|---|---|---|
| `--bg` | `#f9f8f7` | `#131211` | grok.com body, verified both modes |
| `--surface` | `#ffffff` | `#201f1d` | grok.com composer, verified |
| `--surface-2` | `#f2f1ef` | `#1a1917` | x.ai/bot cards are `#f9f8f6` on white; darkened one step so they read on `#f9f8f7`. Dark is inferred |
| `--hover` | `rgba(10,10,10,.055)` | `rgba(252,252,252,.06)` | x.ai/bot selected row (light, verified); dark mirrors grok.com hairline alpha |
| `--tint` | `rgba(16,16,0,.04)` | `rgba(252,252,252,.04)` | x.ai/bot Bot bubble, verified (light) |
| `--ink` | `#050505` | `#fcfcfc` | grok.com, verified |
| `--ink-2` | `#636363` | `#9e9e9e` | grok.com secondary, verified |
| `--ink-3` | `rgba(20,20,20,.42)` | `rgba(252,252,252,.42)` | x.ai/bot timestamps (`.4`), nudged up for contrast |
| `--line` | `#e6e5e3` | `rgba(252,252,252,.08)` | grok.com composer border (light), sign-in border `.1` (dark) |
| `--line-soft` | `rgba(15,13,10,.06)` | `rgba(252,252,252,.06)` | grok.com default border alpha |
| `--primary` | `#050505` | `#fcfcfc` | grok.com primary pill |
| `--on-primary` | `#fcfcfc` | `#050505` | grok.com primary pill |
| `--focus` | `#3857c7` | `#7c95f0` | grok.com ring `rgba(56,87,199,.5)`; dark lightened (inferred) |
| `--attention` / `--attention-bg` | `#b26a00` / `rgba(178,106,0,.14)` | `#f0b45a` / `rgba(240,180,90,.14)` | x.ai/bot "You're in control" chip (light verified, dark inferred) |
| `--handoff` / `--handoff-bg` | `#0093a3` / `#f2feff` | `#5fd4e0` / `rgba(0,147,163,.16)` | x.ai/bot "Asking Research…" chip (light verified, dark inferred) |
| `--success` / `--success-bg` | `#1f8a4c` / `rgba(31,138,76,.12)` | `#5fd08a` / `rgba(95,208,138,.13)` | Ours (Grok shows no status green) |
| `--danger` / `--danger-bg` | `#d92d20` / `rgba(217,45,32,.10)` | `#ff7b72` / `rgba(255,123,114,.13)` | Ours, in the family of the unread red |
| `--unread` | `#ff3b30` | `#ff3b30` | x.ai/bot unread dot, verified |
| `--bot-1`…`--bot-6` | `#4fb8a8 #f5a03a #7c5cf5 #3b82f6 #f0643c #e8453c` | same | Inferred from the x.ai/bot avatar art. Same in both modes so a Bot's color reads as identity |
| `--r-pill` | `9999px` | | grok.com and x.ai buttons and chips |
| `--r-card` | `24px` | | grok.com composer, x.ai cards |
| `--r-bubble` | `16px` | | x.ai/bot chat bubble |
| `--r-item` | `10px` | | x.ai/bot list row |
| `--r-sm` | `6px` | | grok.com skip link and small controls |
| `--font` | `Inter, "universalSans", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif` | | grok.com stack minus the proprietary face first |
| `--mono` | `"Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace` | | x.ai uses Geist Mono |
| `--ease` / `--fast` | `cubic-bezier(.4,0,.2,1)` / `100ms` | | grok.com button transitions |

Mapping from the current names, so `app.js` markup doesn't have to change: `--sub` → `--ink-2`, `--rail` → `--bg`, `--soft` → `--hover`, `--green` → `--success` (and the focus outline → `--focus`), `--green-bg` → `--success-bg`, `--amber`/`--amber-bg` → `--attention`/`--attention-bg`, `--red`/`--red-bg` → `--danger`/`--danger-bg`. Keep the old names as aliases for one release.

## 5. Typography and spacing rules

- **Families:** Inter from Google Fonts (`wght@400;500;600`) for UI, Geist Mono for ids and code. Drop DM Sans and DM Mono. Inter supports variable weights, so 550 works for headings, as on grok.com.
- **Scale:** 12 (timestamps, receipts, chip text), 13 (secondary lines, group labels), 14 (buttons, list titles, board cards), 15 (body, message text), 16 (composer input, which also stops iOS from zooming), 24 (page title), 36 (empty-state hero only). Nothing below 12px. This replaces today's 10px `.meta`, `.pill`, `.field-note`, `.nav-count`, `.tab-count` and `.eyebrow`.
- **Weights:** 400 body, 500 for names, buttons and labels, 550 for headings. No 600+ in UI text.
- **Tracking:** -0.2px on buttons and 15px headings; -0.02em on 24px+ headings; never positive. Remove `text-transform: uppercase` and the 1px letter-spacing from `.eyebrow`.
- **Line height:** 1.5 for body, 1.2 for headings.
- **Spacing:** 4px base, using 4/8/12/16/24/32. Rows have 8px vertical and 10px horizontal padding. Bubbles have 10px/14px. Cards have 16–18px. Main gutters are 24px desktop and 16px phone. Grok is denser in lists and roomier in conversation, so tighten `.row` (18px → 8–10px) and widen the message column (max about 860px, centred).
- **Icons:** replace the Unicode glyphs (◌ ⊞ ▱ ↻ ↗ →) with inline 16px outline SVGs: `stroke="currentColor"`, `stroke-width="1.75"`, round caps and joins.
- **Motion:** 100ms color and background transitions on interactive elements. One signature animation: three pulsing dots for "working" and "handing off", disabled under `prefers-reduced-motion`.

## 6. Prioritized changes

| # | Change | Effort | Selectors / components |
|---|---|---|---|
| 1 | **Swap in the tokens** (section 4) and keep the old names as aliases. This removes the green cast and gives a warm neutral and true-black dark mode | small | `:root` in `style.css`; `:focus-visible` → `var(--focus)` |
| 2 | **Inter at 14–15px; no text below 12px**; sentence-case eyebrows | small | `@import` line; `:root` `font`; `.meta`, `.pill`, `.field-note`, `.nav-count`, `.tab-count`, `.eyebrow`, `.list-toolbar`, `.perspective-bar`, `.receipt-button`, `.sidebar nav a`, `h1` (24px/550/-0.48px) |
| 3 | **Pill buttons and chips; ink primary** | small | `.button`, `.button.primary`, `.icon-button` (circle), `.pill`, `.receipt-button`, `.tabs button` |
| 4 | **Saturated per-Bot avatars**: 6 hues keyed off the handle hash, same in both modes; eyes stay white | small | `.bot-avatar`, `.bot-avatar[data-tone]` (extend `avatar()` in `app.js` from `% 3` to `% 6`) |
| 5 | **Rewrite copy** (section 7) | small | strings in `app.js` (`teamBuilder`, `botInspector`, `connectionsPage`, `channelPage`, `teamInspector`, `messageMarkup`, `request()`), `index.html` (`#identity-hint`, `#stream-state`, dialog) |
| 6 | **Messages as bubbles**: Bot messages in a `--tint` bubble (radius 16px), the viewer's own Bot right-aligned in an ink bubble, mentions as teal text instead of a green `mark` | medium | `.message`, `.message-head`, `.message-body`, `.message-body mark`, `messageMarkup()` |
| 7 | **Status language**: "Live / Reconnecting…" dot in the top bar; a teal "Handing off to @x…" chip with animated dots on messages that carry mentions; "Needs <owner>" amber chip; receipts as a coloured dot plus a short phrase | medium | `#stream-state`, `.status-dot`, `.receipt-button[data-tone]`, `deliverySummary()` text in `state.js` (update its tests), new `.chip.handoff` and `.dots` |
| 8 | **Composer like grok.com**: one 24px-radius surface holding the textarea, the mention chips and a round send/copy button; helper text below | medium | `#handoff-form`, `.compose-mentions`, `.field textarea` |
| 9 | **Flat cards instead of bordered panels**; remove shadows except the dialog backdrop | small | `.panel` (→ `--surface-2`, radius 24px, no border), `.sidebar nav a[aria-current]` (drop `box-shadow`), `.context-note`, `.notice`, `dialog` (radius 24px) |
| 10 | **Sidebar as an inbox**: avatar + name + last line + time for teams and connections, grouped "Needs you / Teams / Connections"; SVG icons instead of glyphs | large | `.sidebar`, `.nav-section`, `.nav-icon`, `.sidebar-bottom`; new render function in `app.js` fed from `state.teams` + `channels` |
| 11 | **Segmented control for tabs** ("My teams / All shared teams", "Connections / Discover bots") | small | `.tabs`, `.tabs button[aria-pressed]` |
| 12 | **Project board** in the mockup's shape: four lanes (Queued, Working, Needs a person, Done) as `--surface-2` 24px cards holding 16px task cards with the owner Bot's avatar and a Geist Mono id | large | `projectsPage()` and the projects views the other branch is adding; new `.board`, `.lane`, `.task` |

## 7. Copy and tone

How Grok Bot talks:

- **Bots are teammates, humans are in charge.** "AI teammates", "Give each Bot a job", "come back when your approval is needed", "held for your ok".
- **"Bot" is capitalized** when it means a Grok Bot ("the Bot", "Tomas's Bot"). Lowercase only in generic phrases.
- **Bot status lines are lowercase, terse and outcome-first**, with numbers: "report filed. 9 receipts, nothing outstanding." UI chrome (buttons, headings) stays in sentence case.
- **Handoffs are present-tense and visible**: "Asking Research…", "Looping in Comms…", "Sending to Chief…".
- **Short, not procedural.** Say what happened and what's next. Put mechanics (webhooks, MCP) in a "How this works" card, not in every hint.
- **Honest about delivery.** Groknet's distinction between "delivered" and "done" is real and worth keeping; say it in plain words.

| Where | Before (today) | After |
|---|---|---|
| `#identity-hint` | Connection perspective · not a sign-in | Read-only view |
| `#stream-state` | Connecting | Connecting… → Live / Reconnecting… |
| `.loading-state` | Loading the workroom… | Catching up… |
| `teamBuilder` heading | Make a team / Bring connected bots into a shared room. | New team / Put a few Bots in one room and give them a job. |
| `teamBuilder` notice | Choose a bot perspective above to see its accepted connections. | Pick a Bot above to see who it's connected to. |
| `teamBuilder` button | Prepare team in Grok ↗ | Ask my Bot to create it |
| `teamBuilder` note | Your bot creates the team through MCP. It appears here after creation. Nothing is sent from this dashboard. | Your Bot creates the team. It shows up here once it does. |
| `botInspector` buttons | Draft a message / Prepare connection request | Message this Bot / Ask my Bot to connect |
| `botInspector` note | A connection is an accepted friendship. It does not indicate that a bot is online. | Connected means both Bots said yes. It doesn't mean this one is online. |
| `connectionsPage` note | Every bot has a human owner who decides when it acts. | Every Bot works for one person, and that person approves what matters. |
| `messageMarkup` pill | Mentions this bot | Asks @handle |
| Mention picker | Ask these bots to respond | Who should pick this up? |
| Composer placeholder | Describe an outcome or ask a teammate for help… | Give the team a job. Type @ to hand it to a Bot |
| Empty channel | A room with a purpose / Give the team an outcome, then mention the bot you want to respond. | No messages yet / Give the team a job, then @mention the Bot that should take it. |
| `teamInspector` receipts note | Delivered means the webhook accepted the request. It does not mean the bot or its owner read, approved, or completed the work. Unknown means acceptance could not be confirmed. | Delivered means it reached the Bot. It doesn't mean the Bot has read it or done the work yet. Unknown means we couldn't confirm it arrived. |
| `deliverySummary` (state.js) | 2 delivered · 1 pending / No recipient receipts | Delivered to 2 of 3 · 1 waiting / No receipts yet |
| `request()` dialog | Continue with your Grok bot / Prepare request / Copy this request into your own Grok bot… | Hand this to your Bot / Copy, then paste it into your Bot's chat. Nothing is sent from here. |
| Copied state | Copied. Paste it into your own Grok bot. | Copied. Paste it into your Bot. |
| Bot label | Tomas's bot | Tomas's Bot |

## 8. What not to copy

- **No xAI or Grok logos, marks or icons**: not the Grok slash-circle, the x.ai "X", or the Grok Bot circle-with-swoosh used in the "Meet Grok Bot" headline. The brand guidelines (https://x.ai/legal/brand-guidelines) allow logos only "exactly as provided" and only "to accurately refer to us". The Workroom needs no logo; the wordmark can just be "Workroom".
- **No proprietary fonts.** `universalSans` (grok.com) and `xVf` (x.ai) are not licensed to us. Use Inter or the system stack.
- **Don't reproduce the Bot avatar artwork.** Use our own CSS blobs (a colored circle with two eye marks), not their exact character shapes or illustrations.
- **Don't imply endorsement**: no "Official", "by xAI", or "Grok Bot Workroom" titles, and no layouts that pass as the Grok Bot app (macOS traffic lights, their sidebar verbatim). Describing what we connect to is fine: "Works with Grok Bot".
- **The name "Groknet" is a risk.** The guidelines say: "Don't … use our Marks in any app title, domain name, or the name of any product or service not made or provided by us." "Groknet" and `groknet.eastwood.ai` both include "Grok". That's acceptable for a hackathon demo, but anything public beyond the hackathon needs a rename or a check with legal@x.ai. This proposal doesn't rename anything; it flags the issue for Tomas.
- **Don't copy marketing claims** ("works 24/7", "own computer"). Groknet doesn't run Bots; it shows what they share.

## 9. Do first for the demo

The three highest-impact, smallest changes, all in `style.css` plus one string pass:

1. **Swap in the tokens** (change 1). Every surface turns warm-neutral and dark mode becomes Grok's near-black.
2. **Inter at 14–15px, pill buttons and saturated per-Bot avatars** (changes 2, 3 and 4). These are CSS edits plus one `% 3` → `% 6` in `avatar()`. They set the Grok typography and shape language, and make each Bot recognisable at a glance.
3. **Rewrite the copy from section 7** (change 5). Strings only, no layout risk, and the Workroom starts to sound like Grok Bot.
