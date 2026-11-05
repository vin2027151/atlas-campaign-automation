## 1. Ranked: the 15 most valuable changes

1. **Home — turn the landing page into an exception queue.**  
   **Problem:** Four KPIs and five navigation cards describe the product, but do not answer “what needs my attention this morning?”  
   **Fix:** Put failing campaigns, final approvals, overdue creative, carried-over checklist items and losing tests above the platform pacing table. Link each exception directly to its control surface; allow final content approval inline.  
   **Why:** The buyer should be able to triage the account without visiting five pages first.  
   **Effort:** M

2. **Management — make “In play” the first working section and add controls.**  
   **Problem:** The 30-day checklist currently pushes the actual account decisions below the fold, and the decision table only links elsewhere.  
   **Fix:** Move “In play” directly under the account-status strip. Add inline two-click pause, a explicit `+10%/day` action for campaigns already classified as scaling, and a direct controls link.  
   **Why:** The page claims to be the morning cockpit; it should support the decision, not merely describe it.  
   **Effort:** M

3. **Spend — put the campaign monitor before the charts and remove low-value columns.**  
   **Problem:** The buyer must pass three platform cards, a funnel and two large charts before reaching the operational table. Its important 3-day CPT monitor starts around column nine.  
   **Fix:** Order the page as summary → campaign monitor → daily spend → rolling CPT → funnel. Reduce the table to decision-relevant columns and fold secondary metadata into the campaign cell.  
   **Why:** Charts explain movement; the table drives action. The monitor should be visible without a long horizontal scroll.  
   **Effort:** M

4. **Global — replace the desktop-only navigation behavior with a coherent responsive shell.**  
   **Problem:** At mobile widths the sidebar footer—and therefore its sample-data and adapter indicators—disappears. Touch targets and page actions are also too small.  
   **Fix:** Add a persistent mobile sample pill, larger touch targets, predictable one/two-column grids, better overflow behavior and a mobile navigation that closes after selection or Escape.  
   **Why:** A dashboard that technically fits 390px but hides critical context is not mobile-compatible.  
   **Effort:** M

5. **Campaigns — simplify the control table and make deep links work.**  
   **Problem:** Fourteen columns mix identity, configuration and performance. Links from Management land on `/campaigns#id`, but the page does nothing with the hash.  
   **Fix:** Keep ten operational columns, move country/type/bid strategy/start date into the campaign cell, expose negative-keyword reviews directly, and open/scroll to hashed campaigns. Replace the session-change vanity KPI with pending negative recommendations.  
   **Why:** Cross-page workflows currently end at a generic list instead of the intended campaign.  
   **Effort:** M

6. **Calendar — create a single approval/overdue queue.**  
   **Problem:** Overdue work, Vin feedback and final approvals are distributed across five board columns, calendar cells and a 14-day list.  
   **Fix:** Add an action queue above the board with direct approval for `final_pending_approval` items. Put the upcoming list before the dense month grid on small screens.  
   **Why:** “What is waiting on me?” should not require visual search across three representations of the same data.  
   **Effort:** M

7. **Reporting — reduce eight competing KPIs to four headline measures.**  
   **Problem:** Eight tiles include immature November paid counts and multiple cohort explanations before the reader reaches exceptions.  
   **Fix:** Headline 7-day PostHog CPT, MTD trials, MTD spend and projected pacing. Keep matured paid economics in the account table where their cohort label is adjacent. Move “What changed” above pacing.  
   **Why:** A report should establish performance and exceptions before explaining every accounting nuance.  
   **Effort:** S

8. **Global — label windows, units and attribution at the point of reading.**  
   **Problem:** Labels such as `Spend`, `Trials`, `CPT 3d`, and `Pace` require subtitles or prior knowledge to interpret.  
   **Fix:** Use labels such as `PostHog trials (7d)`, `Cost / trial (3d)`, `Spend (selected window)` and `Projected spend / budget`. Keep CPT, CPA and percentage-point deltas distinct.  
   **Why:** The same number means different things in a 3-day monitor, an MTD report and an apportioned ad-set row.  
   **Effort:** S

9. **Global — make thin reads visible rather than coloring them as confidently good or bad.**  
   **Problem:** A CPT based on one or two trials receives the same visual authority as one based on fifty.  
   **Fix:** Show trial denominators in titles and visible `n=` / `0 trials` caveats on the main monitoring surfaces. Preserve em dashes for undefined ratios.  
   **Why:** Small-count CPT is usually the easiest way to make a bad pause or scale decision.  
   **Effort:** S

10. **Global — fix light/dark contrast and provide an explicit theme control.**  
    **Problem:** The current CSS advertises light support through `data-theme="light"` but nothing sets it. Some light-theme purple text is too faint, while muted dark-theme text is inconsistent.  
    **Fix:** Default to a near-white light theme, honor `prefers-color-scheme: dark`, add a persistent manual toggle, and update Chart.js colors after switching.  
    **Why:** Theme support should be real, not dormant CSS.  
    **Effort:** M

11. **Global — complete keyboard interaction.**  
    **Problem:** Tabs are click-oriented, the checklist day rail has listbox semantics without arrow-key behavior, and mobile navigation lacks close-on-select behavior.  
    **Fix:** Add arrow/Home/End navigation for tab lists and the checklist rail, retain visible focus, and preserve Enter/Space campaign expansion and Escape cancellation.  
    **Why:** Keyboard support is especially valuable in dense operational tables where repeated mouse travel is expensive.  
    **Effort:** S

12. **Home/Reporting — clarify pacing semantics.**  
    **Problem:** “Pace” mixes MTD performance, projected month-end and straight-line plan in different places.  
    **Fix:** Name the metric `Projected spend / budget`, show projected dollars next to it, and retain budget-to-date and daily target only in the detailed pacing view.  
    **Why:** A 101% projection and 101% MTD budget consumption are different conditions requiring different responses.  
    **Effort:** S

13. **Calendar/Management — reduce duplicated test presentation without deleting information.**  
    **Problem:** Both pages render large test scoreboards, lengthening two already dense pages.  
    **Fix:** Keep Calendar focused on schedule and pipeline, label its lower test section as schedule context, and link to Management for the full win/loss ledger.  
    **Why:** The buyer needs one authoritative operational scoreboard, not two equally prominent interpretations.  
    **Effort:** S

14. **Global — improve empty, null and failure states.**  
    **Problem:** Some empty areas are helpful, while others are only skeletons, em dashes or generic failure toasts.  
    **Fix:** Add actionable empty states to the new queues, preserve server-error callouts, keep zero-denominator values as em dashes, and avoid displaying zero as a missing value.  
    **Why:** “No urgent work,” “no data,” and “request failed” require different responses.  
    **Effort:** S

15. **Reporting/Global — make print output match the actual shell.**  
    **Problem:** Print CSS hides `.topbar`, which the current layout no longer uses, so the sidebar can leak into printed reports.  
    **Fix:** Hide the real navigation/theme chrome, remove the sidebar offset, preserve card boundaries and retain the sample-data disclosure.  
    **Why:** Exported reports should not contain broken navigation or be mistaken for live-account evidence.  
    **Effort:** S

---

## 2. Per-page critique and recommended above-the-fold order

### Home

**Critique:** It is currently a site map with KPIs. The four numbers are useful, but the page does not exploit the existing Management and Calendar APIs to surface exceptions. Platform pacing is more prominent than work requiring a decision.

**1440 order:**
1. Compact page heading and sample-data date.
2. Four KPIs: 7-day CPT, MTD trials, MTD spend, projected pacing.
3. Two-column working area: exception queue at roughly 60%, platform pacing at 40%.
4. Navigation cards as secondary shortcuts.

**390 order:**
1. Heading.
2. KPIs in a 2×2 grid.
3. Exception queue with full-width actions.
4. Platform pacing in horizontal table overflow.
5. Navigation shortcuts.

### Spend

**Critique:** This is an analysis page before it is an operations page. The funnel and charts are polished, but they bury the highest-value table. Fourteen columns make the 3-day monitor hard to find.

**1440 order:**
1. Window selector with literal dates.
2. Account/Google/Meta summary cards.
3. Campaign monitor table with 3-day and 7-day CPT near the left.
4. Daily spend chart.
5. Rolling 3-day CPT chart.
6. Account funnel and allocation/paid-lag notes.

**390 order:**
1. Horizontally scrollable window selector.
2. Account total, then Google and Meta cards.
3. Campaign monitor table in deliberate horizontal overflow.
4. Daily chart.
5. Rolling CPT chart.
6. Vertically stacked funnel.

### Calendar

**Critique:** The board is a good pipeline representation, but all five statuses receive equal visual priority. The person opening the page usually needs overdue and approval work, not the entire inventory. The month grid is weak on a phone.

**1440 order:**
1. `New content item` action.
2. Overdue/approval/feedback queue.
3. Board with summary counts.
4. Calendar and next-14-days views.
5. Test schedule context and link to Management.

**390 order:**
1. New-item action.
2. Action queue.
3. Board, one column at a time.
4. Next-14-days list.
5. Month grid.
6. Test schedule.

### Reporting

**Critique:** Eight KPIs overstate the importance of immature paid data and dilute the report’s main read. “What changed” is too low for an exception-oriented report. The data-trust treatment is strong and should remain.

**1440 order:**
1. Export and print actions.
2. Four headline KPIs.
3. What changed this week.
4. Detailed pacing.
5. Spend/trials and rolling-CPT charts.
6. Account table with matured-cohort paid economics.
7. Platform-versus-PostHog trust cards.

**390 order:**
1. Full-width export/print actions.
2. Four KPIs in a 2×2 grid.
3. Changes.
4. Pacing cards with stacked stats.
5. Charts, one per row.
6. Horizontally scrollable account table.
7. Trust cards.

### Management

**Critique:** This has the best decision model in the product, but its presentation order undersells it. Checklist administration precedes failing/scaling campaigns, and campaign decisions require another page.

**1440 order:**
1. Account-status strip: CPT, pace, today’s checklist and carry-over.
2. In-play table with read counts and campaign actions.
3. Today/carried-over checklist, with the 30-day rail as navigation.
4. Tests scoreboard and ledger.
5. Tracking.
6. Lessons and activity.

**390 order:**
1. Account-status tiles.
2. Read counts and in-play table.
3. Carried-over items, then today’s checklist.
4. Test cards.
5. Tracking.
6. Lesson composer and activity.

### Campaigns

**Critique:** This is correctly the control surface, but configuration metadata crowds out performance. Activity takes a full desktop rail even before the user has changed anything. Cross-page campaign links are unfinished.

**1440 order:**
1. Summary tiles, including negative-keyword recommendations.
2. Sticky platform/status/search toolbar.
3. Compact campaign control table and expandable panels.
4. Activity rail.

**390 order:**
1. Summary in two columns.
2. Full-width search and wrapping filters.
3. Campaign table in horizontal overflow; expansion panels remain full width.
4. Activity below the table.

---

## 3. Code

The following replacements and diffs use only the existing API responses and mutations.

### `static/css/app.css` — complete replacement

```css
/* Atlas Ops design system.
   Tokens -> base -> shell -> primitives -> components -> utilities -> responsive.
   Existing page class names are retained; page-specific styles remain in templates. */

/* ------------------------------------------------------------------ tokens */
:root {
  color-scheme: light;
  --sa-purple: #936BDA;
  --sa-purple-soft: #AA85EC;
  --sa-purple-dark: #653A9D;
  --sa-purple-darker: #351E57;
  --sa-mint: #00FFD4;
  --sa-ink-900: #121212;
  --sa-ink-850: #17181B;
  --sa-ink-750: #24262A;
  --sa-gray: #A3A4A4;
  --sa-gray-light: #E8E8E8;
  --sa-red: #F44343;
  --sa-yellow: #F1AA3E;

  --bg: #f5f4f8;
  --surface: #ffffff;
  --surface-2: #f2f0f7;
  --surface-3: #e8e4f1;
  --ink: #17181b;
  --ink-2: #3d404b;
  --muted: #686c79;
  --line: #e1dee9;
  --line-strong: #c9c4d5;

  --accent: #653A9D;
  --accent-ink: #ffffff;
  --accent-soft: rgba(101, 58, 157, .09);
  --accent-line: rgba(101, 58, 157, .34);
  --mint: #00a98f;
  --mint-ink: #121212;

  --good: #087866;
  --good-soft: #e2f6f1;
  --good-line: #98d9cb;
  --watch: #936006;
  --watch-soft: #fdf1dc;
  --watch-line: #eacb92;
  --bad: #bd2929;
  --bad-soft: #fce9e9;
  --bad-line: #ecb4b4;
  --idle: #656975;
  --idle-soft: #eeeeF3;
  --idle-line: #d2d3dc;

  --google: #1769d2;
  --google-soft: #e6effc;
  --meta: #653A9D;
  --meta-soft: #eee8f8;

  --series-1: #653A9D;
  --series-2: #087866;
  --series-3: #1769d2;
  --series-4: #a56a08;
  --series-5: #c73535;
  --series-6: #8b5fc4;

  --font: "Inter", "Inter Tight", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-display: "Inter Tight", "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  --fs-xs: 11px;
  --fs-sm: 12px;
  --fs: 13px;
  --fs-md: 14px;
  --fs-lg: 16px;
  --fs-xl: 22px;
  --fs-kpi: 28px;
  --lh: 1.5;

  --r-sm: 6px;
  --r: 8px;
  --r-lg: 12px;
  --r-pill: 999px;
  --s1: 4px;
  --s2: 8px;
  --s3: 12px;
  --s4: 16px;
  --s5: 24px;
  --s6: 32px;
  --shadow: 0 1px 2px rgba(16, 24, 40, .06);
  --shadow-pop: 0 10px 30px rgba(16, 24, 40, .18);
  --focus: 0 0 0 3px rgba(147, 107, 218, .38);
  --maxw: 1440px;
  --sidebar-w: 248px;
  --topbar-h: 56px;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #0b0b0d;
    --surface: #17181b;
    --surface-2: #1e2025;
    --surface-3: #292c32;
    --ink: rgba(255, 255, 255, .94);
    --ink-2: rgba(255, 255, 255, .76);
    --muted: #a9abb4;
    --line: rgba(255, 255, 255, .10);
    --line-strong: rgba(255, 255, 255, .19);
    --accent: #b899ed;
    --accent-ink: #17181b;
    --accent-soft: rgba(147, 107, 218, .17);
    --accent-line: rgba(170, 133, 236, .46);
    --mint: #00FFD4;
    --mint-ink: #121212;
    --good: #46e6c9;
    --good-soft: rgba(0, 255, 212, .10);
    --good-line: rgba(0, 255, 212, .34);
    --watch: #f3bc64;
    --watch-soft: rgba(241, 170, 62, .13);
    --watch-line: rgba(241, 170, 62, .40);
    --bad: #ff7979;
    --bad-soft: rgba(244, 67, 67, .13);
    --bad-line: rgba(244, 67, 67, .42);
    --idle: #b1b3bc;
    --idle-soft: rgba(163, 164, 164, .11);
    --idle-line: rgba(163, 164, 164, .31);
    --google: #9abcff;
    --google-soft: rgba(138, 180, 255, .13);
    --meta: #c0a3f1;
    --meta-soft: rgba(170, 133, 236, .15);
    --series-1: #AA85EC;
    --series-2: #00FFD4;
    --series-3: #8ab4ff;
    --series-4: #F1AA3E;
    --series-5: #ff7979;
    --series-6: #c4a6ef;
    --shadow: 0 1px 2px rgba(0, 0, 0, .42);
    --shadow-pop: 0 10px 30px rgba(0, 0, 0, .58);
  }
}

:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #0b0b0d;
  --surface: #17181b;
  --surface-2: #1e2025;
  --surface-3: #292c32;
  --ink: rgba(255, 255, 255, .94);
  --ink-2: rgba(255, 255, 255, .76);
  --muted: #a9abb4;
  --line: rgba(255, 255, 255, .10);
  --line-strong: rgba(255, 255, 255, .19);
  --accent: #b899ed;
  --accent-ink: #17181b;
  --accent-soft: rgba(147, 107, 218, .17);
  --accent-line: rgba(170, 133, 236, .46);
  --mint: #00FFD4;
  --mint-ink: #121212;
  --good: #46e6c9;
  --good-soft: rgba(0, 255, 212, .10);
  --good-line: rgba(0, 255, 212, .34);
  --watch: #f3bc64;
  --watch-soft: rgba(241, 170, 62, .13);
  --watch-line: rgba(241, 170, 62, .40);
  --bad: #ff7979;
  --bad-soft: rgba(244, 67, 67, .13);
  --bad-line: rgba(244, 67, 67, .42);
  --idle: #b1b3bc;
  --idle-soft: rgba(163, 164, 164, .11);
  --idle-line: rgba(163, 164, 164, .31);
  --google: #9abcff;
  --google-soft: rgba(138, 180, 255, .13);
  --meta: #c0a3f1;
  --meta-soft: rgba(170, 133, 236, .15);
  --series-1: #AA85EC;
  --series-2: #00FFD4;
  --series-3: #8ab4ff;
  --series-4: #F1AA3E;
  --series-5: #ff7979;
  --series-6: #c4a6ef;
  --shadow: 0 1px 2px rgba(0, 0, 0, .42);
  --shadow-pop: 0 10px 30px rgba(0, 0, 0, .58);
}

:root[data-theme="light"] { color-scheme: light; }

/* -------------------------------------------------------------------- base */
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
  font: var(--fs)/var(--lh) var(--font);
  letter-spacing: -.011em;
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3, h4 {
  margin: 0;
  font-family: var(--font-display);
  font-weight: 600;
  letter-spacing: -.015em;
}
h1 { font-size: var(--fs-xl); }
h2 { font-size: var(--fs-lg); }
h3 { font-size: var(--fs-md); }
p { margin: 0 0 var(--s2); }
p:last-child { margin-bottom: 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
button, input, select, textarea { font: inherit; }
button { touch-action: manipulation; }
small, .small { font-size: var(--fs-sm); }
code, .mono { font-family: var(--mono); font-size: .92em; }
hr { border: 0; border-top: 1px solid var(--line); margin: var(--s4) 0; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: var(--r-sm); }
::selection { background: rgba(147, 107, 218, .35); }
[hidden], .hidden { display: none !important; }
.skip {
  position: fixed;
  left: -999px;
  top: 8px;
  z-index: 300;
  padding: 8px 12px;
  border-radius: var(--r-pill);
  background: var(--sa-mint);
  color: var(--sa-ink-900);
  font-weight: 700;
}
.skip:focus { left: 8px; }
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

/* ------------------------------------------------------------------ sidebar */
.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  width: var(--sidebar-w);
  color: rgba(255, 255, 255, .92);
  background: var(--sa-ink-900);
  border-right: 1px solid rgba(255, 255, 255, .10);
}
.sidebar-top {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s5) var(--s4) var(--s4);
  border-bottom: 1px solid rgba(255, 255, 255, .10);
}
.brand { display: block; flex: none; }
.brand:hover { text-decoration: none; }
.brand-logo { display: block; width: 168px; height: auto; }
.brand-title { display: flex; flex: 1; flex-direction: column; min-width: 0; margin-top: var(--s3); gap: 2px; }
.brand-title-main {
  color: var(--sa-mint);
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .12em;
  text-transform: uppercase;
}
.brand-title-by { color: #a9abb4; font-size: var(--fs-sm); }
.sidebar-top { flex-wrap: wrap; }
.sidebar-top .brand, .sidebar-top .brand-title { flex-basis: 100%; }
.sidebar-toggle { display: none; }
.sidebar-tools { display: flex; align-items: center; gap: var(--s2); margin-left: auto; }
.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 32px;
  padding: 0 8px;
  border: 1px solid rgba(255, 255, 255, .18);
  border-radius: var(--r-pill);
  color: #fff;
  background: transparent;
  cursor: pointer;
}
.theme-toggle:hover { background: rgba(255, 255, 255, .08); }
.mobile-sample { display: none; }
.sidebar-nav {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  padding: var(--s3) var(--s2);
}
.nav-link {
  display: flex;
  align-items: center;
  gap: var(--s3);
  min-height: 42px;
  padding: 9px var(--s3);
  border: 0;
  border-left: 2px solid transparent;
  border-radius: var(--r);
  color: rgba(255, 255, 255, .74);
  font-weight: 500;
  white-space: nowrap;
}
.nav-link:hover { color: #fff; background: rgba(255, 255, 255, .06); text-decoration: none; }
.nav-link.active {
  color: #fff;
  background: rgba(147, 107, 218, .20);
  border-left-color: var(--sa-mint);
  font-weight: 600;
}
.nav-icon {
  position: relative;
  display: grid;
  flex: none;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 5px;
  background: var(--sa-ink-750);
}
.nav-icon::before { content: ""; width: 8px; height: 8px; border-radius: 2px; background: var(--sa-purple-soft); }
.nav-link.active .nav-icon::before { background: var(--sa-mint); }
.nav-icon[data-icon="home"]::before { border-radius: 50%; }
.nav-icon[data-icon="spend"]::before { width: 10px; height: 6px; }
.nav-icon[data-icon="calendar"]::before { width: 10px; height: 8px; border-top: 2px solid var(--sa-ink-900); }
.nav-icon[data-icon="reporting"]::before { width: 4px; height: 10px; box-shadow: 6px 2px 0 0 var(--sa-purple-soft); }
.nav-link.active .nav-icon[data-icon="reporting"]::before { box-shadow: 6px 2px 0 0 var(--sa-mint); }
.nav-icon[data-icon="management"]::before {
  width: 10px;
  height: 2px;
  box-shadow: 0 4px 0 0 var(--sa-purple-soft), 0 -4px 0 0 var(--sa-purple-soft);
}
.nav-link.active .nav-icon[data-icon="management"]::before {
  box-shadow: 0 4px 0 0 var(--sa-mint), 0 -4px 0 0 var(--sa-mint);
}
.nav-icon[data-icon="campaigns"]::before {
  width: 0;
  height: 0;
  border-top: 5px solid transparent;
  border-bottom: 5px solid transparent;
  border-left: 8px solid var(--sa-purple-soft);
  border-radius: 0;
  background: none;
}
.nav-link.active .nav-icon[data-icon="campaigns"]::before { border-left-color: var(--sa-mint); }
.sidebar-foot {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s3) var(--s4);
  border-top: 1px solid rgba(255, 255, 255, .10);
  color: #a9abb4;
  font-size: var(--fs-sm);
}
.sidebar-date { font-variant-numeric: tabular-nums; }
.sidebar-adapter { font-size: var(--fs-xs); }

/* retained legacy hooks */
.topbar, .topbar-inner, .topbar-meta { display: contents; }
.topbar-date { color: var(--muted); font-size: var(--fs-sm); font-variant-numeric: tabular-nums; }

/* ------------------------------------------------------------------- shell */
.shell { display: flex; flex-direction: column; min-height: 100vh; margin-left: var(--sidebar-w); }
.main { flex: 1; width: 100%; max-width: var(--maxw); margin: 0 auto; padding: var(--s5); }
.main > * + * { margin-top: var(--s4); }
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s4);
  flex-wrap: wrap;
  margin-bottom: var(--s1);
}
.page-title { font-size: var(--fs-xl); font-weight: 600; }
.page-sub { max-width: 88ch; margin-top: var(--s1); color: var(--muted); }
.page-actions { display: flex; align-items: center; gap: var(--s2); flex-wrap: wrap; }
.footer { margin-top: var(--s6); border-top: 1px solid var(--line); background: var(--surface); }
.footer-inner {
  display: flex;
  align-items: center;
  gap: var(--s4);
  flex-wrap: wrap;
  max-width: var(--maxw);
  margin: 0 auto;
  padding: var(--s3) var(--s5);
  color: var(--ink-2);
  font-size: var(--fs-sm);
}

/* --------------------------------------------------------------- primitives */
.stack { display: flex; flex-direction: column; gap: var(--s4); }
.stack-sm { display: flex; flex-direction: column; gap: var(--s2); }
.stack-lg { display: flex; flex-direction: column; gap: var(--s5); }
.row { display: flex; align-items: center; gap: var(--s2); flex-wrap: wrap; }
.row-between { display: flex; align-items: center; justify-content: space-between; gap: var(--s3); flex-wrap: wrap; }
.spacer { flex: 1; }
.grid { display: grid; gap: var(--s4); }
.grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.grid-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.grid-auto { grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }
.grid-main-side { grid-template-columns: minmax(0, 1fr) 340px; }
.span-2 { grid-column: span 2; }
.span-all { grid-column: 1 / -1; }
.kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.kpi-grid.kpi-5 { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.kpi-grid.kpi-6 { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.page-grid { grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
.home-ops { display: grid; grid-template-columns: minmax(0, 3fr) minmax(330px, 2fr); gap: var(--s4); align-items: start; }

/* -------------------------------------------------------------------- card */
.card {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  flex-wrap: wrap;
  min-height: 44px;
  padding: var(--s3) var(--s4);
  border-bottom: 1px solid var(--line);
}
.card-title { font-size: var(--fs-md); font-weight: 600; }
.card-sub { color: var(--muted); font-size: var(--fs-sm); font-weight: 400; }
.card-body { padding: var(--s4); }
.card-body.tight { padding: var(--s3); }
.card-foot { padding: var(--s2) var(--s4); border-top: 1px solid var(--line); color: var(--muted); font-size: var(--fs-sm); }
.card > .table-wrap { border: 0; border-radius: 0 0 var(--r-lg) var(--r-lg); }
.card-link { display: block; color: inherit; transition: border-color .12s, box-shadow .12s; }
.card-link:hover { border-color: var(--accent-line); box-shadow: 0 0 0 1px var(--accent-line); text-decoration: none; }
.card-link-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: var(--s1); }
.card-link .arrow { color: var(--muted); }
.card-link:hover .arrow { color: var(--accent); }
.chart-box { position: relative; height: 260px; }
.chart-box.sm { height: 180px; }
.chart-box.lg { height: 340px; }

/* --------------------------------------------------------------------- KPI */
.kpi {
  min-width: 0;
  padding: var(--s3) var(--s4);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.kpi-label {
  overflow: hidden;
  color: var(--muted);
  font-size: var(--fs-sm);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kpi-value { margin-top: 2px; font-size: var(--fs-kpi); font-weight: 600; line-height: 1.2; letter-spacing: -.01em; }
.kpi-value.num { text-align: left; }
.kpi-sub { margin-top: 3px; color: var(--muted); font-size: var(--fs-sm); }
.kpi-delta { font-size: var(--fs-sm); font-weight: 600; }
.kpi-delta.up { color: var(--good); }
.kpi-delta.down { color: var(--bad); }
.kpi-bar { height: 4px; margin-top: var(--s2); overflow: hidden; border-radius: 2px; background: var(--surface-3); }
.kpi-bar > span { display: block; height: 100%; border-radius: 2px; background: var(--accent); }
.tone-good { color: var(--good); }
.tone-watch { color: var(--watch); }
.tone-bad { color: var(--bad); }
.tone-idle { color: var(--idle); }

/* ------------------------------------------------------------------- table */
.table-wrap {
  max-width: 100%;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}
.table-wrap.scroll { max-height: 560px; }
.table { width: 100%; border-spacing: 0; border-collapse: separate; font-size: var(--fs); }
.table th, .table td {
  padding: 7px var(--s3);
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: middle;
  white-space: nowrap;
}
.table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  border-bottom: 1px solid var(--line-strong);
  color: var(--ink-2);
  background: var(--surface-2);
  font-size: var(--fs-sm);
  font-weight: 600;
}
.table thead th.sortable { cursor: pointer; user-select: none; }
.table thead th.sortable:hover { color: var(--ink); }
.table thead th[aria-sort="ascending"]::after { content: " \25B4"; }
.table thead th[aria-sort="descending"]::after { content: " \25BE"; }
.table tbody tr:nth-child(even) td { background: color-mix(in srgb, var(--surface-2) 55%, var(--surface)); }
.table tbody tr:hover td { background: var(--surface-3); }
.table tbody tr:last-child td { border-bottom: 0; }
.table tfoot td { border-top: 1px solid var(--line-strong); border-bottom: 0; background: var(--surface-2); font-weight: 600; }
.table .num, .num { text-align: right; font-variant-numeric: tabular-nums; font-feature-settings: "tnum" 1; }
.table td.wrap, .table th.wrap { min-width: 220px; white-space: normal; }
.table td.actions { width: 1%; text-align: right; }
.table tr.is-paused td { color: var(--muted); }
.table tr.is-selected td { background: var(--accent-soft); }
.table tr.indent-1 td:first-child { padding-left: calc(var(--s3) + 18px); }
.table tr.indent-2 td:first-child { padding-left: calc(var(--s3) + 36px); }
.table.compact th, .table.compact td { padding: 5px var(--s2); }
.table-empty { padding: var(--s5); color: var(--muted); text-align: center; }
.caveat { color: var(--watch); font-size: var(--fs-xs); font-weight: 600; }

/* ----------------------------------------------------------- badges/chips */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 20px;
  padding: 0 7px;
  border: 1px solid var(--idle-line);
  border-radius: 10px;
  color: var(--idle);
  background: var(--idle-soft);
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: .02em;
  text-transform: uppercase;
  white-space: nowrap;
  vertical-align: middle;
}
.badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.badge.plain::before { display: none; }
.badge.active, .badge.won, .badge.approved, .badge.good { color: var(--good); background: var(--good-soft); border-color: var(--good-line); }
.badge.running, .badge.scheduled, .badge.info { color: var(--accent); background: var(--accent-soft); border-color: var(--accent-line); }
.badge.watch, .badge.pending_feedback, .badge.final_pending_approval, .badge.inconclusive { color: var(--watch); background: var(--watch-soft); border-color: var(--watch-line); }
.badge.lost, .badge.bad, .badge.error { color: var(--bad); background: var(--bad-soft); border-color: var(--bad-line); }
.badge.paused, .badge.queued, .badge.idle { color: var(--idle); background: var(--idle-soft); border-color: var(--idle-line); }
.pill {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  white-space: nowrap;
}
.pill-sample { border: 1px solid var(--accent-line); color: var(--accent); background: var(--accent-soft); }
.sidebar .pill-sample { color: var(--sa-mint); border-color: rgba(0, 255, 212, .35); background: rgba(0, 255, 212, .08); }
.chip {
  display: inline-grid;
  flex: none;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  vertical-align: -3px;
}
.chip-google { color: var(--google); background: var(--google-soft); }
.chip-meta { color: var(--meta); background: var(--meta-soft); }
.tag {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  color: var(--ink-2);
  background: var(--surface-2);
  font-size: var(--fs-xs);
  white-space: nowrap;
}

/* ----------------------------------------------------------------- buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r);
  color: var(--ink);
  background: var(--surface);
  font: 500 var(--fs)/1 var(--font);
  cursor: pointer;
  white-space: nowrap;
  transition: background .1s, border-color .1s, color .1s;
}
.btn:hover { background: var(--surface-2); text-decoration: none; }
.btn:active { background: var(--surface-3); }
.btn:disabled, .btn.is-busy { opacity: .55; cursor: not-allowed; }
.btn-primary { border-color: var(--sa-mint); border-radius: var(--r-pill); color: var(--sa-ink-900); background: var(--sa-mint); font-weight: 700; }
.btn-primary:hover { border-color: #4dffe1; background: #4dffe1; }
.btn-ghost { border-color: transparent; color: var(--ink-2); background: transparent; }
.btn-ghost:hover { color: var(--ink); background: var(--surface-2); }
.btn-danger { border-color: var(--bad-line); color: var(--bad); background: var(--surface); }
.btn-danger:hover { background: var(--bad-soft); }
.btn-sm { min-height: 26px; padding: 0 8px; border-radius: var(--r-sm); font-size: var(--fs-sm); }
.btn-icon { width: 32px; padding: 0; }
.btn-sm.btn-icon { width: 26px; }
.btn.is-confirming { border-color: var(--bad); color: #fff; background: var(--bad); animation: confirm-pulse 1.2s ease-in-out infinite; }
@keyframes confirm-pulse { 50% { box-shadow: 0 0 0 3px var(--bad-soft); } }
.btn-group { display: inline-flex; max-width: 100%; }
.btn-group .btn { margin-left: -1px; border-radius: 0; }
.btn-group .btn:first-child { margin-left: 0; border-radius: var(--r) 0 0 var(--r); }
.btn-group .btn:last-child { border-radius: 0 var(--r) var(--r) 0; }
.btn-group .btn.active { z-index: 1; border-color: var(--accent-line); color: var(--accent); background: var(--accent-soft); }

/* ------------------------------------------------------------------- forms */
.input, .select, .textarea {
  min-width: 0;
  height: 32px;
  padding: 0 var(--s2);
  border: 1px solid var(--line-strong);
  border-radius: var(--r);
  color: var(--ink);
  background: var(--surface);
  font: var(--fs)/1.2 var(--font);
}
.textarea { width: 100%; height: auto; min-height: 72px; padding: var(--s2); line-height: var(--lh); resize: vertical; }
.input:focus, .select:focus, .textarea:focus { border-color: var(--accent); outline: none; box-shadow: var(--focus); }
.input.num { width: 110px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field > label, .label { color: var(--ink-2); font-size: var(--fs-sm); font-weight: 500; }
.field-hint { color: var(--muted); font-size: var(--fs-sm); }
.check { display: inline-flex; align-items: center; gap: var(--s2); cursor: pointer; }
.check input { width: 15px; height: 15px; margin: 0; accent-color: var(--accent); }

/* -------------------------------------------------------------------- tabs */
.tabs { display: flex; gap: 2px; overflow-x: auto; border-bottom: 1px solid var(--line); scrollbar-width: none; }
.tabs::-webkit-scrollbar { display: none; }
.tab {
  appearance: none;
  margin-bottom: -1px;
  padding: var(--s2) var(--s3);
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--ink-2);
  background: none;
  font: 500 var(--fs)/1.2 var(--font);
  cursor: pointer;
  white-space: nowrap;
}
.tab:hover { color: var(--ink); }
.tab.active, .tab[aria-selected="true"] { border-bottom-color: var(--accent); color: var(--ink); font-weight: 600; }
.tab .count { margin-left: 4px; color: var(--muted); font-weight: 500; font-variant-numeric: tabular-nums; }
.tab-panel[hidden] { display: none; }

/* ------------------------------------------------------------------- modal */
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 10vh var(--s4) var(--s4);
  background: rgba(10, 14, 20, .52);
  animation: fade-in .12s ease-out;
}
.modal {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 520px;
  max-height: 80vh;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  box-shadow: var(--shadow-pop);
}
.modal.wide { max-width: 760px; }
.modal-head { display: flex; align-items: center; justify-content: space-between; padding: var(--s3) var(--s4); border-bottom: 1px solid var(--line); }
.modal-title { font-size: var(--fs-md); font-weight: 600; }
.modal-body { overflow: auto; padding: var(--s4); }
.modal-foot { display: flex; justify-content: flex-end; gap: var(--s2); padding: var(--s3) var(--s4); border-top: 1px solid var(--line); }
@keyframes fade-in { from { opacity: 0; } }

/* ------------------------------------------------------------------- toast */
.toast-stack {
  position: fixed;
  right: var(--s4);
  bottom: var(--s4);
  z-index: 200;
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  width: min(360px, calc(100vw - 2 * var(--s4)));
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: flex-start;
  gap: var(--s2);
  padding: var(--s2) var(--s3);
  border-left: 4px solid var(--good);
  border-radius: var(--r);
  color: var(--surface);
  background: var(--ink);
  box-shadow: var(--shadow-pop);
  font-size: var(--fs);
  pointer-events: auto;
  animation: toast-in .16s ease-out;
}
:root[data-theme="light"] .toast { color: #fff; background: #24262a; }
.toast.error { border-left-color: var(--bad); }
.toast.warn { border-left-color: var(--watch); }
.toast.info { border-left-color: var(--accent); }
.toast.leaving { opacity: 0; transform: translateY(4px); transition: opacity .2s, transform .2s; }
@keyframes toast-in { from { opacity: 0; transform: translateY(6px); } }

/* -------------------------------------------------------------- action queue */
.action-list { list-style: none; margin: 0; padding: 0; }
.action-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border-bottom: 1px solid var(--line);
}
.action-item:last-child { border-bottom: 0; }
.action-copy { min-width: 0; }
.action-title { font-weight: 600; overflow-wrap: anywhere; }
.action-meta { margin-top: 2px; color: var(--muted); font-size: var(--fs-sm); }
.action-controls { display: flex; align-items: center; justify-content: flex-end; gap: var(--s2); flex-wrap: wrap; }
.action-empty { padding: var(--s5); color: var(--muted); }

/* ------------------------------------------------------------ misc/helpers */
.empty { padding: var(--s5); color: var(--muted); text-align: center; }
.callout { padding: var(--s3) var(--s4); border: 1px solid var(--accent-line); border-radius: var(--r-lg); color: var(--ink); background: var(--accent-soft); }
.callout.watch { border-color: var(--watch-line); background: var(--watch-soft); }
.callout.bad { border-color: var(--bad-line); background: var(--bad-soft); }
.callout.good { border-color: var(--good-line); background: var(--good-soft); }
.meter { height: 6px; min-width: 60px; overflow: hidden; border-radius: 3px; background: var(--surface-3); }
.meter > span { display: block; height: 100%; background: var(--accent); }
.meter.good > span { background: var(--good); }
.meter.watch > span { background: var(--watch); }
.meter.bad > span { background: var(--bad); }
.dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px var(--s4); margin: 0; }
.dl dt { color: var(--muted); }
.dl dd { margin: 0; }
.list { list-style: none; margin: 0; padding: 0; }
.list > li { padding: var(--s2) 0; border-bottom: 1px solid var(--line); }
.list > li:last-child { border-bottom: 0; }
.skeleton {
  min-height: 14px;
  border-radius: var(--r-sm);
  background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2));
  background-size: 200% 100%;
  animation: shimmer 1.2s infinite;
}
@keyframes shimmer { to { background-position: -200% 0; } }
.muted { color: var(--muted); }
.ink-2 { color: var(--ink-2); }
.strong { font-weight: 600; }
.nowrap { white-space: nowrap; }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.right { text-align: right; }
.center { text-align: center; }
.mt-0 { margin-top: 0 !important; }
.mt-2 { margin-top: var(--s2); }
.mt-4 { margin-top: var(--s4); }

/* --------------------------------------------------------------- responsive */
@media (max-width: 1180px) {
  .kpi-grid.kpi-5, .kpi-grid.kpi-6 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .grid-4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .grid-main-side, .home-ops { grid-template-columns: minmax(0, 1fr); }
}

@media (max-width: 1023px) {
  .sidebar {
    position: sticky;
    top: 0;
    inset: auto;
    width: auto;
    border-right: 0;
    border-bottom: 1px solid rgba(255, 255, 255, .12);
  }
  .sidebar-top { flex-wrap: nowrap; min-height: var(--topbar-h); padding: var(--s2) var(--s4); }
  .sidebar-top .brand { flex-basis: auto; }
  .sidebar-top .brand-title { flex-basis: auto; margin: 0; }
  .brand-logo { width: 126px; }
  .brand-title-main { overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
  .brand-title-by { display: none; }
  .mobile-sample { display: inline-flex; margin-left: auto; }
  .sidebar-tools { margin-left: 0; }
  .sidebar-toggle {
    display: inline-flex;
    flex-direction: column;
    justify-content: center;
    gap: 4px;
    width: 38px;
    height: 38px;
    padding: 0 9px;
    border: 1px solid rgba(255, 255, 255, .18);
    border-radius: var(--r);
    background: transparent;
    cursor: pointer;
  }
  .sidebar-toggle span { display: block; height: 2px; border-radius: 2px; background: #fff; }
  .sidebar-nav { display: none; padding: var(--s2); }
  .sidebar-foot { display: none; }
  .sidebar.open .sidebar-nav { display: flex; }
  .sidebar.open .sidebar-foot { display: flex; flex-direction: row; align-items: center; flex-wrap: wrap; }
  .shell { margin-left: 0; }
}

@media (max-width: 820px) {
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .grid-2, .grid-3 { grid-template-columns: minmax(0, 1fr); }
  .span-2 { grid-column: auto; }
  .topbar-date { display: none; }
  .main { padding: var(--s4); }
  .page-head { align-items: flex-start; }
}

@media (max-width: 640px) {
  :root { --fs-kpi: 23px; --topbar-h: auto; }
  .brand-title { display: none; }
  .mobile-sample { margin-left: auto; }
  .main { padding: var(--s3); }
  .main > * + * { margin-top: var(--s3); }
  .footer-inner { gap: var(--s2); padding: var(--s3); }
  .grid-4, .kpi-grid.kpi-5, .kpi-grid.kpi-6 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kpi-grid { gap: var(--s2); }
  .kpi { padding: var(--s2) var(--s3); }
  .kpi-label { white-space: normal; }
  .card-head, .card-body { padding-right: var(--s3); padding-left: var(--s3); }
  .page-actions { width: 100%; }
  .page-actions .btn { min-height: 38px; }
  .page-actions .btn-group { max-width: 100%; overflow-x: auto; }
  .page-actions .btn-group .btn { min-height: 36px; }
  .chart-box { height: 220px; }
  .chart-box.lg { height: 280px; }
  .modal-backdrop { padding-top: var(--s4); }
  .action-item { grid-template-columns: auto minmax(0, 1fr); padding: var(--s3); }
  .action-controls { grid-column: 2; justify-content: flex-start; }
  .table th, .table td { padding: 6px var(--s2); }
  .toast-stack { right: var(--s3); bottom: var(--s3); }
}

@media (max-width: 390px) {
  .sidebar-top { padding-right: var(--s3); padding-left: var(--s3); }
  .brand-logo { width: 112px; }
  .theme-toggle { min-width: 30px; height: 30px; padding: 0 6px; }
  .page-grid { grid-template-columns: minmax(0, 1fr); }
  .kpi-value { font-size: 21px; }
  .action-item { gap: var(--s2); }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
}

@media print {
  .sidebar, .footer, .page-actions, .toast-stack, .theme-toggle { display: none !important; }
  .shell { margin-left: 0; }
  .main { max-width: none; padding: 0; }
  .card, .kpi { box-shadow: none; }
}
```

### `templates/base.html` — complete replacement

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark light">
  <title>{% block title %}{{ title }}{% endblock %} · Atlas Ops</title>
  <link rel="icon" href="/static/img/favicon.svg" type="image/svg+xml">
  <script>
    (function () {
      try {
        var saved = localStorage.getItem("atlas.theme");
        if (saved === "light" || saved === "dark") {
          document.documentElement.setAttribute("data-theme", saved);
        }
      } catch (e) { /* Storage may be unavailable; system preference still works. */ }
    })();
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap">
  <link rel="stylesheet" href="/static/css/app.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
  <script type="module" src="/static/js/common.js"></script>
  {% block head %}{% endblock %}
</head>
<body class="page-{{ page }}" data-page="{{ page }}" data-today="{{ today }}">
  <a class="skip" href="#main">Skip to content</a>

  <aside class="sidebar" id="sidebar" aria-label="Primary">
    <div class="sidebar-top">
      <a class="brand" href="/" aria-label="Atlas Ops home">
        <img class="brand-logo" src="/static/img/searchatlas-wordmark-white.svg" alt="Search Atlas" width="202" height="16">
      </a>
      <div class="brand-title">
        <span class="brand-title-main">Atlas Ops</span>
        <span class="brand-title-by">Paid media · by Vincent J. Guarino III</span>
      </div>
      <span class="pill pill-sample mobile-sample" title="Every number is generated sample data; no ad account is connected.">Sample data</span>
      <div class="sidebar-tools">
        <button class="theme-toggle" id="theme-toggle" type="button" aria-label="Switch color theme" title="Switch color theme">◐</button>
        <button class="sidebar-toggle" id="sidebar-toggle" type="button" aria-expanded="false" aria-controls="sidebar-nav" aria-label="Open navigation">
          <span></span><span></span><span></span>
        </button>
      </div>
    </div>

    <nav class="sidebar-nav" id="sidebar-nav" aria-label="Pages">
      {% for item in nav %}
      <a href="{{ item.path }}" class="nav-link nav-{{ item.name }}{% if item.name == page %} active{% endif %}"{% if item.name == page %} aria-current="page"{% endif %}>
        <span class="nav-icon" aria-hidden="true" data-icon="{{ item.name }}"></span>
        <span class="nav-label">{{ item.label }}</span>
      </a>
      {% endfor %}
    </nav>

    <div class="sidebar-foot">
      <span class="pill pill-sample" title="Every number is generated sample data; no ad account is connected.">Sample data</span>
      <span class="sidebar-date" title="Sample-data date">As of {{ today }}</span>
      <span class="sidebar-adapter">Adapter: {{ meta.adapter or "local" }}</span>
    </div>
  </aside>

  <div class="shell">
    <main class="main" id="main" tabindex="-1">
      {% block header %}
      <div class="page-head">
        <div>
          <h1 class="page-title">{{ title }}</h1>
          {% block subtitle %}{% endblock %}
        </div>
        <div class="page-actions">{% block actions %}{% endblock %}</div>
      </div>
      {% endblock %}
      {% block content %}{% endblock %}
    </main>

    <footer class="footer">
      <div class="footer-inner">
        <span class="pill pill-sample">Sample data</span>
        <span>Search Atlas paid media · Google Ads + Meta · as of {{ today }}</span>
        <span class="muted">Platform adapter: {{ meta.adapter or "local" }} sample state, not a live account</span>
      </div>
    </footer>
  </div>

  <div class="toast-stack" id="toast-stack" aria-live="polite"></div>

  <script>
    (function () {
      var toggle = document.getElementById("sidebar-toggle");
      var sidebar = document.getElementById("sidebar");
      var nav = document.getElementById("sidebar-nav");

      function setNav(open) {
        if (!toggle || !sidebar) return;
        sidebar.classList.toggle("open", open);
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
      }

      if (toggle && sidebar) {
        toggle.addEventListener("click", function () {
          setNav(!sidebar.classList.contains("open"));
        });
      }
      if (nav) {
        nav.addEventListener("click", function (event) {
          if (event.target.closest("a")) setNav(false);
        });
      }

      var themeButton = document.getElementById("theme-toggle");
      function currentTheme() {
        var explicit = document.documentElement.getAttribute("data-theme");
        if (explicit === "light" || explicit === "dark") return explicit;
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      }
      function updateThemeLabel() {
        if (!themeButton) return;
        var next = currentTheme() === "dark" ? "light" : "dark";
        themeButton.setAttribute("aria-label", "Switch to " + next + " theme");
        themeButton.setAttribute("title", "Switch to " + next + " theme");
      }
      if (themeButton) {
        updateThemeLabel();
        themeButton.addEventListener("click", function () {
          var next = currentTheme() === "dark" ? "light" : "dark";
          document.documentElement.setAttribute("data-theme", next);
          try { localStorage.setItem("atlas.theme", next); } catch (e) { /* non-fatal */ }
          updateThemeLabel();
          if (window.atlas && window.atlas.chartDefaults) window.atlas.chartDefaults();
          if (window.Chart && window.Chart.instances) {
            Object.values(window.Chart.instances).forEach(function (chart) { chart.update("none"); });
          }
        });
      }

      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") setNav(false);
      });

      /* Arrow-key behavior for every tab list, including platform filters. */
      document.addEventListener("keydown", function (event) {
        var tab = event.target.closest && event.target.closest('[role="tablist"] .tab');
        if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        var list = Array.from(tab.closest('[role="tablist"]').querySelectorAll(".tab:not(:disabled)"));
        var index = list.indexOf(tab);
        if (index < 0 || !list.length) return;
        event.preventDefault();
        var nextIndex;
        if (event.key === "Home") nextIndex = 0;
        else if (event.key === "End") nextIndex = list.length - 1;
        else nextIndex = (index + (event.key === "ArrowRight" ? 1 : -1) + list.length) % list.length;
        list[nextIndex].focus();
        list[nextIndex].click();
      });
    })();
  </script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

### `templates/home.html` — complete replacement

```html
{% extends "base.html" %}
{% block subtitle %}
<p class="page-sub">Morning brief for {{ today }}. Trials are PostHog-attributed signups; cost-per-trial decisions use the {{ "${:,.0f}".format(meta.cpa_target[0]) }}–{{ "${:,.0f}".format(meta.cpa_target[1]) }} target band.</p>
{% endblock %}
{% block content %}
{% set cpa = meta.cpa_target %}
<section class="grid kpi-grid" aria-label="Headline numbers">
  <div class="kpi">
    <div class="kpi-label">Cost / PostHog trial (7d)</div>
    {% set c7 = kpis.cpt_7d %}
    <div class="kpi-value num {% if c7 is none %}{% elif c7 <= cpa[1] %}tone-good{% elif c7 <= cpa[1] * 1.15 %}tone-watch{% else %}tone-bad{% endif %}">
      {% if c7 is none %}&mdash;{% else %}{{ "${:,.0f}".format(c7) }}{% endif %}
    </div>
    <div class="kpi-sub">{{ kpis.trials_7d }} trials · target {{ "${:,.0f}".format(cpa[0]) }}–{{ "${:,.0f}".format(cpa[1]) }}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">PostHog trials (MTD)</div>
    <div class="kpi-value num">{{ "{:,}".format(kpis.trials_mtd) }}</div>
    <div class="kpi-sub">{{ kpis.trials_7d }} in the trailing 7 days</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Spend, USD (MTD)</div>
    <div class="kpi-value num">{{ "${:,.0f}".format(kpis.mtd_spend) }}</div>
    <div class="kpi-sub">of {{ "${:,.0f}".format(kpis.monthly_budget) }} monthly budget</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Projected spend / budget</div>
    {% set pp = kpis.pace_pct %}
    <div class="kpi-value num {% if pp is none %}{% elif 95 <= pp <= 105 %}tone-good{% elif 90 <= pp <= 110 %}tone-watch{% else %}tone-bad{% endif %}">
      {% if pp is none %}&mdash;{% else %}{{ "{:.1f}%".format(pp) }}{% endif %}
    </div>
    <div class="kpi-sub">{{ "${:,.0f}".format(kpis.projected) }} projected at the 7-day daily rate</div>
  </div>
</section>

<div class="home-ops">
  <section class="card" aria-labelledby="home-queue-title">
    <div class="card-head">
      <h2 class="card-title" id="home-queue-title">Needs a decision</h2>
      <span class="card-sub" id="home-queue-sub">Checking account state…</span>
    </div>
    <div id="home-queue" aria-live="polite">
      <div class="card-body"><div class="skeleton" style="height:180px"></div></div>
    </div>
  </section>

  <section class="card" aria-labelledby="home-pacing-title">
    <div class="card-head">
      <h2 class="card-title" id="home-pacing-title">Pacing by platform</h2>
      <span class="card-sub">day {{ kpis.days_elapsed }} of {{ kpis.days_in_month }}</span>
    </div>
    <div class="table-wrap">
      <table class="table compact">
        <thead>
          <tr>
            <th>Platform</th>
            <th class="num">Spent MTD</th>
            <th class="num">7d spend / day</th>
            <th class="num">Projected</th>
            <th class="num">Proj. / budget</th>
          </tr>
        </thead>
        <tbody>
        {% for pl, p in kpis.platforms.items() %}
          <tr>
            <td><span class="chip chip-{{ pl }}">{{ "G" if pl == "google" else "M" }}</span> {{ "Google" if pl == "google" else "Meta" }}</td>
            <td class="num" title="Monthly budget {{ "${:,.0f}".format(p.monthly_budget) }}">{{ "${:,.0f}".format(p.month_to_date_spend) }}</td>
            <td class="num">{{ "${:,.0f}".format(p.daily_rate_7d) }}</td>
            <td class="num">{{ "${:,.0f}".format(p.projected_month_end) }}</td>
            <td class="num">{% if p.pace_pct is none %}&mdash;{% else %}{{ "{:.1f}%".format(p.pace_pct) }}{% endif %}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    <div class="card-foot">Projection = MTD spend + trailing-7-day daily spend × days remaining. <a href="/reporting">Detailed pacing →</a></div>
  </section>
</div>

<section class="grid page-grid" aria-label="Pages">
  {% for item in nav if item.name != "home" %}
  <a class="card card-link" href="{{ item.path }}">
    <div class="card-body">
      <div class="card-link-head"><h2 class="card-title">{{ item.title }}</h2><span class="arrow" aria-hidden="true">&rarr;</span></div>
      <p class="muted">{{ item.description }}</p>
    </div>
  </a>
  {% endfor %}
</section>
{% endblock %}
{% block scripts %}
<script type="module" src="/static/js/home.js"></script>
{% endblock %}
```

### `static/js/home.js` — new complete file

```javascript
// Home: a cross-page exception queue assembled from existing Management and
// Calendar responses. Final content approvals use the existing move mutation.
import { api, fmt, toast, esc, badge, platformChip, cptTone, $ } from "/static/js/common.js";

let management = null;
let calendar = null;

function actionItem({ tone = "idle", label, title, meta, href, linkText = "Review", approveId = null }) {
  const controls = approveId
    ? `<button class="btn btn-sm btn-primary" type="button" data-home-approve="${esc(approveId)}">Approve</button>
       <a class="btn btn-sm" href="/calendar">Open</a>`
    : `<a class="btn btn-sm" href="${esc(href)}">${esc(linkText)}</a>`;
  return `<li class="action-item">
    ${badge(tone, label)}
    <div class="action-copy">
      <div class="action-title">${title}</div>
      <div class="action-meta">${meta}</div>
    </div>
    <div class="action-controls">${controls}</div>
  </li>`;
}

function campaignAction(c) {
  const trials = Number(c.trials_7d || 0);
  const thin = trials < 3 ? " · thin read" : "";
  return actionItem({
    tone: "bad",
    label: "Failing",
    title: `${platformChip(c.platform)} ${esc(c.name)}`,
    meta: `7d CPT <strong class="${cptTone(c.cpt_7d)}">${fmt.cpt(c.cpt_7d)}</strong> · ${fmt.money(c.spend_7d)} spend · ${fmt.int(trials)} trials${thin}. ${esc(c.why)}`,
    href: `/campaigns#${encodeURIComponent(c.id)}`,
    linkText: "Controls",
  });
}

function buildActions() {
  const actions = [];
  const active = management.in_play.groups.flatMap((g) => g.campaigns);
  active.filter((c) => c.read === "failing")
    .sort((a, b) => (b.spend_7d || 0) - (a.spend_7d || 0))
    .forEach((c) => actions.push(campaignAction(c)));

  const seenContent = new Set();
  calendar.overdue.forEach((item) => {
    seenContent.add(item.id);
    actions.push(actionItem({
      tone: "bad",
      label: "Overdue",
      title: esc(item.name),
      meta: `${esc(item.owner)} · due ${fmt.date(item.due)} · ${esc(item.status_label)}`,
      href: "/calendar",
      linkText: "Open board",
    }));
  });

  calendar.content.filter((item) => item.status === "final_pending_approval" && !seenContent.has(item.id))
    .forEach((item) => {
      seenContent.add(item.id);
      actions.push(actionItem({
        tone: "watch",
        label: "Approval",
        title: esc(item.name),
        meta: `${platformChip(item.platform)} ${esc(item.owner)} · due ${fmt.date(item.due)} · ${esc(item.format)} / ${esc(item.segment)}`,
        approveId: item.id,
      }));
    });

  calendar.content.filter((item) => item.status === "pending_feedback" && !seenContent.has(item.id))
    .slice(0, 3)
    .forEach((item) => actions.push(actionItem({
      tone: "watch",
      label: "Feedback",
      title: esc(item.name),
      meta: `${esc(item.owner)} · due ${fmt.date(item.due)} · waiting on Vin`,
      href: "/calendar",
      linkText: "Review",
    })));

  management.tests.running.filter((t) => t.verdict === "losing").forEach((t) => {
    actions.push(actionItem({
      tone: "bad",
      label: "Test",
      title: esc(t.name),
      meta: `${esc(t.campaign_name || t.campaign_id)} · ${esc(t.verdict_note)}`,
      href: "/management#mg-tests",
      linkText: "Scoreboard",
    }));
  });

  const carry = management.today.carry_over || 0;
  if (carry) {
    actions.push(actionItem({
      tone: "watch",
      label: "Checklist",
      title: `${carry} checklist item${carry === 1 ? "" : "s"} carried over`,
      meta: "Open work from earlier days is still incomplete.",
      href: "/management#mg-checklist",
      linkText: "Clear items",
    }));
  }

  const pace = management.today.pace_pct;
  if (pace !== null && pace !== undefined && (pace > 105 || pace < 90)) {
    actions.push(actionItem({
      tone: "bad",
      label: "Pacing",
      title: `Account projecting at ${fmt.pct(pace)} of budget`,
      meta: `${fmt.money(management.today.projected)} projected against ${fmt.money(management.today.monthly_budget)}.`,
      href: "/reporting",
      linkText: "Pacing",
    }));
  }

  return actions;
}

function renderQueue() {
  const actions = buildActions();
  const failing = management.in_play.counts.failing || 0;
  const approvals = calendar.content.filter((c) => c.status === "final_pending_approval").length;
  const overdue = calendar.overdue.length;
  $("#home-queue-sub").textContent = `${failing} failing · ${approvals} final approval${approvals === 1 ? "" : "s"} · ${overdue} overdue`;

  if (!actions.length) {
    $("#home-queue").innerHTML = `<div class="action-empty">
      <strong>No urgent exceptions.</strong>
      <div class="mt-2">Review watching campaigns, today’s checklist and upcoming creative before making budget changes.</div>
      <div class="row mt-4"><a class="btn btn-sm" href="/management">Open morning cockpit</a><a class="btn btn-sm" href="/calendar">Content schedule</a></div>
    </div>`;
    return;
  }

  const visible = actions.slice(0, 8);
  const remainder = actions.length - visible.length;
  $("#home-queue").innerHTML = `<ul class="action-list">${visible.join("")}</ul>` +
    (remainder > 0 ? `<div class="card-foot">${remainder} more lower-priority item${remainder === 1 ? "" : "s"} on Management and Calendar.</div>` : "");
}

async function loadBrief() {
  try {
    [management, calendar] = await Promise.all([api("/api/management/"), api("/api/calendar/")]);
    renderQueue();
  } catch (e) {
    $("#home-queue-sub").textContent = "Could not refresh";
    $("#home-queue").innerHTML = `<div class="card-body"><div class="callout bad">
      The exception queue could not load: ${esc(e.message)}. KPI tiles above are still available.
      <div class="mt-2"><button class="btn btn-sm" type="button" id="home-retry">Retry</button></div>
    </div></div>`;
    toast("Could not load the morning brief: " + e.message, "error");
  }
}

$("#home-queue").addEventListener("click", async (event) => {
  if (event.target.closest("#home-retry")) {
    await loadBrief();
    return;
  }
  const button = event.target.closest("[data-home-approve]");
  if (!button) return;
  const id = button.dataset.homeApprove;
  const item = calendar && calendar.content.find((c) => c.id === id);
  button.disabled = true;
  try {
    await api(`/api/calendar/content/${encodeURIComponent(id)}/move`, { body: { status: "approved" } });
    toast(`Approved: ${item ? item.name : id}`);
    await loadBrief();
  } catch (e) {
    toast("Could not approve item: " + e.message, "error");
    button.disabled = false;
  }
});

loadBrief();
```

### `templates/management.html` — unified diff

```diff
--- a/templates/management.html
+++ b/templates/management.html
@@ -116,9 +116,9 @@
   <div class="table-wrap">
     <table class="table compact">
-      <thead><tr><th>Campaign</th><th class="num">Daily budget</th><th class="num">7d spend</th><th class="num">7d CPT</th><th class="num">Trials 7d</th><th>Read</th><th>Why</th></tr></thead>
-      <tbody id="mg-inplay-body"><tr><td colspan="7" class="table-empty">Loading&hellip;</td></tr></tbody>
+      <thead><tr><th>Campaign</th><th class="num">Budget / day</th><th class="num">Spend (7d)</th><th class="num">Cost / trial (7d)</th><th class="num">PostHog trials (7d)</th><th>Read</th><th>Evidence</th><th class="actions">Actions</th></tr></thead>
+      <tbody id="mg-inplay-body"><tr><td colspan="8" class="table-empty">Loading&hellip;</td></tr></tbody>
     </table>
   </div>
@@ -128,6 +128,7 @@
 <section class="card" id="mg-tests" aria-labelledby="mg-tests-title">
+  <span id="mg-tests-anchor"></span>
   <div class="card-head">
```

### `static/js/management.js` — unified diff

```diff
--- a/static/js/management.js
+++ b/static/js/management.js
@@ -3,7 +3,13 @@
 // lessons update the UI immediately, then reconcile with the server response.
-import { api, fmt, toast, esc, badge, cptTone, platformChip, $ } from "/static/js/common.js";
+import { api, fmt, toast, esc, badge, cptTone, platformChip, confirmButton, $, $$ } from "/static/js/common.js";
+
+/* Account decisions precede checklist administration in visual and keyboard order. */
+(function prioritizeInPlay() {
+  const checklist = $("#mg-checklist");
+  const inPlay = $("#mg-inplay");
+  if (checklist && inPlay) checklist.parentNode.insertBefore(inPlay, checklist);
+})();
 
 const S = { data: null, selectedDay: null, tag: null, newLesson: null };
@@ -153,11 +159,12 @@
     rows.push(`<tr class="mg-group-row"><td>${platformChip(g.platform)} ${esc(g.label)} <span class="muted">&middot; ${g.campaigns.length} active</span></td>
       <td class="num">${fmt.money(t.daily_budget)}</td><td class="num">${fmt.money(t.spend_7d)}</td>
-      <td class="num ${cptTone(t.cpt_7d, band)}">${fmt.cpt(t.cpt_7d)}</td><td class="num">${fmt.int(t.trials_7d)}</td><td></td><td></td></tr>`);
-    if (!g.campaigns.length) rows.push(`<tr><td colspan="7" class="muted">No active campaigns.</td></tr>`);
+      <td class="num ${cptTone(t.cpt_7d, band)}">${fmt.cpt(t.cpt_7d)}</td><td class="num">${fmt.int(t.trials_7d)}</td><td></td><td></td><td></td></tr>`);
+    if (!g.campaigns.length) rows.push(`<tr><td colspan="8" class="muted">No active campaigns.</td></tr>`);
     g.campaigns.forEach((c) => {
       const tags = [c.legacy ? `<span class="tag" title="Legacy campaign running at reduced budget alongside the new build">legacy</span>` : "",
         c.country && c.country !== "US" ? `<span class="tag">${esc(c.country)}</span>` : ""].join("");
+      const thin = c.trials_7d < 3 ? `<div class="caveat">${c.trials_7d === 0 ? "0 trials: CPT undefined" : `n=${c.trials_7d}: thin read`}</div>` : "";
       rows.push(`<tr>
         <td class="mg-camp">${platformChip(c.platform)} ${campLink(c.id, c.name)}${tags} <span class="muted small">${esc(c.type || "")}</span></td>
         <td class="num">${fmt.money(c.daily_budget)}</td>
         <td class="num">${fmt.money(c.spend_7d)}</td>
-        <td class="num strong ${cptTone(c.cpt_7d, band)}">${fmt.cpt(c.cpt_7d)}</td>
+        <td class="num strong ${cptTone(c.cpt_7d, band)}" title="${fmt.money(c.spend_7d)} divided by ${c.trials_7d} PostHog trials">${fmt.cpt(c.cpt_7d)}${thin}</td>
         <td class="num">${fmt.int(c.trials_7d)}</td>
         <td>${readPill(c.read, c.why)}</td>
-        <td class="mg-why">${esc(c.why)}</td></tr>`);
+        <td class="mg-why">${esc(c.why)}</td>
+        <td class="actions"><span class="row-actions">
+          ${c.read === "scaling" ? `<button class="btn btn-sm" type="button" data-mg-scale="${esc(c.id)}" title="Raise daily budget from ${fmt.money(c.daily_budget)} to ${fmt.money(Math.round(c.daily_budget * 110) / 100)}">+10% / day</button>` : ""}
+          <button class="btn btn-sm btn-danger" type="button" data-mg-pause="${esc(c.id)}" data-name="${esc(c.name)}" data-confirm-label="Confirm pause?">Pause</button>
+          <a class="btn btn-sm" href="/campaigns#${encodeURIComponent(c.id)}">Controls</a>
+        </span></td></tr>`);
     });
   });
   $("#mg-inplay-body").innerHTML = rows.join("");
+  $$("#mg-inplay-body [data-mg-pause]").forEach((button) => confirmButton(button, async (el) => {
+    await api(`/api/campaigns/${encodeURIComponent(el.dataset.mgPause)}/status`, { body: { status: "PAUSED" } });
+    toast(`${el.dataset.name} paused`);
+    await load({ quiet: true });
+  }));
@@ -236,6 +243,43 @@
 $("#mg-refresh").addEventListener("click", async () => { await load({ quiet: true }); toast("Refreshed", "info"); });
+
+$("#mg-inplay").addEventListener("click", async (event) => {
+  const button = event.target.closest("[data-mg-scale]");
+  if (!button) return;
+  const id = button.dataset.mgScale;
+  const campaign = S.data.in_play.groups.flatMap((g) => g.campaigns).find((c) => c.id === id);
+  if (!campaign) return;
+  const next = Math.round(Number(campaign.daily_budget) * 110) / 100;
+  button.disabled = true;
+  try {
+    await api(`/api/campaigns/${encodeURIComponent(id)}/budget`, { body: { daily_budget: next } });
+    toast(`${campaign.name}: daily budget ${fmt.money(campaign.daily_budget)} → ${fmt.money(next)}`);
+    await load({ quiet: true });
+  } catch (e) {
+    toast("Could not scale budget: " + e.message, "error");
+    button.disabled = false;
+  }
+});
+
+$("#mg-rail").addEventListener("keydown", (event) => {
+  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
+  const days = S.data.checklist.days;
+  if (!days.length) return;
+  event.preventDefault();
+  let index = days.findIndex((d) => d.day === S.selectedDay);
+  if (event.key === "Home") index = 0;
+  else if (event.key === "End") index = days.length - 1;
+  else index = Math.max(0, Math.min(days.length - 1, index + (event.key === "ArrowRight" ? 1 : -1)));
+  S.selectedDay = days[index].day;
+  renderChecklist();
+  scrollRailTo(S.selectedDay, true);
+  const selected = $(`#mg-rail [data-day="${S.selectedDay}"]`);
+  if (selected) selected.focus();
+});
 
 load().then(() => S.data && scrollRailTo(S.selectedDay, false));
```

### `templates/campaigns.html` — unified diff

```diff
--- a/templates/campaigns.html
+++ b/templates/campaigns.html
@@ -58,17 +58,15 @@
         <thead>
           <tr>
-            <th></th><th>Campaign</th><th>Ctry</th><th>Type</th><th>Status</th>
+            <th></th><th>Campaign</th><th>Status</th>
             <th class="num" title="Click to edit">Daily budget</th>
-            <th class="num" title="Daily budget x days in month">Monthly</th>
-            <th class="num">7d spend</th><th class="num">7d trials</th><th class="num">7d CPT</th><th class="num">3d CPT</th>
-            <th>Bid strategy</th><th>Start</th><th class="actions"></th>
+            <th class="num">Spend (7d)</th><th class="num">PostHog trials (7d)</th><th class="num">Cost / trial (7d)</th><th class="num">Cost / trial (3d)</th>
+            <th>Search-term waste</th><th class="actions"></th>
           </tr>
         </thead>
-        <tbody id="cmp-body"><tr><td colspan="14" class="table-empty">Loading campaigns&hellip;</td></tr></tbody>
+        <tbody id="cmp-body"><tr><td colspan="10" class="table-empty">Loading campaigns&hellip;</td></tr></tbody>
       </table>
@@ -63,5 +61,5 @@
-    <div class="card-foot" id="cmp-foot">CPT = PostHog-attributed cost per trial. Target {{ "${:,.0f}".format(meta.cpa_target[0]) }}&ndash;{{ "${:,.0f}".format(meta.cpa_target[1]) }}.</div>
+    <div class="card-foot" id="cmp-foot">CPT = spend ÷ PostHog-attributed trials. Target {{ "${:,.0f}".format(meta.cpa_target[0]) }}&ndash;{{ "${:,.0f}".format(meta.cpa_target[1]) }}. Country, type, bid strategy and start date sit under the campaign name.</div>
```

### `static/js/campaigns.js` — unified diff

```diff
--- a/static/js/campaigns.js
+++ b/static/js/campaigns.js
@@ -20,7 +20,7 @@
   lastSeenTs: null,
 };
 
-const COLS = 14;
+const COLS = 10;
 const fmtBudget = (v) => fmt.money(v);
@@ -79,10 +79,11 @@
     ${plat("google", "Google")}
     ${plat("meta", "Meta")}
-    <div class="kpi"><div class="kpi-label">Changes this session</div><div class="kpi-value num">${fmt.int(s.changes_this_session)}</div>
-      <div class="kpi-sub" title="Activity entries since the server started (${esc(s.session_start)})">since ${esc(fmt.datetime(s.session_start))}</div></div>`;
+    <div class="kpi"><div class="kpi-label">Negative keywords to review</div><div class="kpi-value num ${S.campaigns.some((c) => c.recommended_negatives) ? "tone-watch" : "tone-good"}">${fmt.int(S.campaigns.reduce((sum, c) => sum + (c.recommended_negatives || 0), 0))}</div>
+      <div class="kpi-sub">recommended terms not yet negated</div></div>`;
 }
@@ -123,35 +124,40 @@
   body.innerHTML = rows.map((c) => {
     const open = S.open.has(c.id);
-    const recs = c.recommended_negatives ? ` <span class="tag" title="Recommended negatives waiting">${c.recommended_negatives} neg</span>` : "";
+    const thin = c.trials_7d < 3 ? `<div class="caveat">${c.trials_7d === 0 ? "0 trials: CPT undefined" : `n=${c.trials_7d}: thin read`}</div>` : "";
+    const negatives = c.platform !== "google"
+      ? `<span class="muted">n/a</span>`
+      : c.recommended_negatives
+        ? `<button class="btn btn-sm" type="button" data-review-neg="${esc(c.id)}">${c.recommended_negatives} recommendation${c.recommended_negatives === 1 ? "" : "s"}</button>`
+        : `<span class="tone-good">None pending</span>`;
     const main = `<tr class="${c.status === "PAUSED" ? "is-paused" : ""}${open ? " is-open" : ""}" data-cid="${esc(c.id)}">
       <td>${platformChip(c.platform)}</td>
-      <td class="name">${esc(c.name)}${c.legacy ? ' <span class="tag">legacy</span>' : ""}${recs}</td>
-      <td>${esc(c.country)}</td>
-      <td>${esc(c.type)}</td>
+      <td class="name">${esc(c.name)}${c.legacy ? ' <span class="tag">legacy</span>' : ""}
+        <div class="small muted">${esc(c.country)} · ${esc(c.type)} · ${esc(c.bid_strategy)} · started ${fmt.date(c.start_date)}</div></td>
       <td>${badge(c.status)}</td>
       <td class="num" data-budget-cell="${esc(c.id)}"><button class="budget-btn" data-budget="${esc(c.id)}" title="Click to edit daily budget">${fmtBudget(c.daily_budget)}</button></td>
-      <td class="num muted" title="Derived: daily x days in month">${fmt.money(c.monthly_budget)}</td>
       <td class="num">${fmt.money(c.spend_7d)}</td>
       <td class="num">${fmt.int(c.trials_7d)}</td>
-      <td class="num ${cptTone(c.cpt_7d, S.cpa)}">${fmt.cpt(c.cpt_7d)}</td>
+      <td class="num ${cptTone(c.cpt_7d, S.cpa)}" title="${fmt.money(c.spend_7d)} divided by ${c.trials_7d} trials">${fmt.cpt(c.cpt_7d)}${thin}</td>
       <td class="num ${cptTone(c.cpt_3d, S.cpa)}">${fmt.cpt(c.cpt_3d)}</td>
-      <td class="bid" title="${esc(c.bid_strategy)}">${esc(c.bid_strategy)}</td>
-      <td class="muted">${fmt.date(c.start_date)}</td>
+      <td>${negatives}</td>
       <td class="actions"><span class="row-actions">
         ${statusBtn("campaign", c.id, c.status, c.name)}
-        <button class="btn btn-sm expand-btn" data-expand="${esc(c.id)}" aria-expanded="${open}">${open ? "Close" : "Expand"}</button>
+        <button class="btn btn-sm expand-btn" data-expand="${esc(c.id)}" aria-expanded="${open}" aria-label="${open ? "Close" : "Expand"} ${esc(c.name)}">${open ? "Close" : "Expand"}</button>
       </span></td></tr>`;
@@ -213,6 +219,13 @@
     const exp = t.closest("[data-expand]");
+    const reviewNeg = t.closest("[data-review-neg]");
+    if (reviewNeg) {
+      const id = reviewNeg.dataset.reviewNeg;
+      S.open.add(id);
+      S.panelTab[id] = "terms";
+      renderTable();
+      await loadDetail(id);
+      renderTable();
+      return;
+    }
     if (exp) {
@@ -257,6 +270,34 @@
 }
 
+async function openFromHash() {
+  const id = decodeURIComponent(window.location.hash.replace(/^#/, ""));
+  if (!id) return;
+  const campaign = S.campaigns.find((c) => c.id === id);
+  if (!campaign) {
+    toast("That campaign is not in the current account state.", "warn");
+    return;
+  }
+  S.platform = "all";
+  S.filters.clear();
+  S.q = "";
+  $("#cmp-search").value = "";
+  $$("#cmp-platform-tabs .tab").forEach((tab) => {
+    const on = tab.dataset.platform === "all";
+    tab.classList.toggle("active", on);
+    tab.setAttribute("aria-selected", on);
+  });
+  $$(".fchip").forEach((chip) => chip.setAttribute("aria-pressed", "false"));
+  S.open.add(id);
+  render();
+  if (!S.details[id]) await loadDetail(id);
+  render();
+  const row = $(`#cmp-body tr[data-cid="${CSS.escape(id)}"]`);
+  if (row) {
+    row.scrollIntoView({ block: "center", behavior: "smooth" });
+    const expand = row.querySelector("[data-expand]");
+    if (expand) expand.focus({ preventScroll: true });
+  }
+}
+
 wire();
-loadAll().catch((e) => {
+window.addEventListener("hashchange", openFromHash);
+loadAll().then(openFromHash).catch((e) => {
   toast(e.message, "error");
```

### `templates/spend.html` — unified diff

```diff
--- a/templates/spend.html
+++ b/templates/spend.html
@@ -117,17 +117,14 @@
         <tr>
           <th></th>
           <th class="sortable" data-key="name">Campaign</th>
-          <th class="sortable" data-key="country">Country</th>
           <th class="sortable" data-key="status">Status</th>
           <th class="sortable num" data-key="daily_budget">Budget / day</th>
-          <th class="sortable num" data-key="spend">Spend</th>
-          <th class="sortable num" data-key="spend_per_day">Spend / day</th>
-          <th class="sortable num" data-key="trials">Trials</th>
-          <th class="sortable num monitor-head" data-key="cpt_3d" title="Trailing 3 days ending today, whatever the window">CPT 3d</th>
-          <th class="sortable num" data-key="cpt_7d" title="Trailing 7 days ending today">CPT 7d</th>
+          <th class="sortable num" data-key="spend">Spend (window)</th>
+          <th class="sortable num" data-key="trials">PostHog trials</th>
+          <th class="sortable num monitor-head" data-key="cpt_3d" title="Trailing 3 days ending today, whatever the window">Cost / trial (3d)</th>
+          <th class="sortable num" data-key="cpt_7d" title="Trailing 7 days ending today">Cost / trial (7d)</th>
           <th class="sortable num" data-key="paid">Paid</th>
-          <th class="sortable num" data-key="trial_to_paid">Trial&rarr;paid</th>
           <th class="sortable num" data-key="cost_per_paid">Cost / paid</th>
           <th class="sortable num" data-key="platform_vs_posthog_pct" title="Platform-reported conversions, and as % of PostHog trials. Flagged outside 80-120%.">Platform conv. vs PostHog</th>
         </tr>
       </thead>
-      <tbody id="camp-body"><tr><td colspan="14" class="table-empty">Loading&hellip;</td></tr></tbody>
+      <tbody id="camp-body"><tr><td colspan="11" class="table-empty">Loading&hellip;</td></tr></tbody>
```

### `static/js/spend.js` — unified diff

```diff
--- a/static/js/spend.js
+++ b/static/js/spend.js
@@ -287,75 +287,71 @@
   let html = "";
   GROUPS.forEach((g) => {
@@ -297,10 +297,9 @@
     const t = sumRows(rows);
     html += `<tr class="group-row${g.legacy ? " legacy" : ""}">
-      <td colspan="4">${g.legacy ? "&#9888; " : ""}${esc(g.label)} · ${rows.length} campaign${rows.length === 1 ? "" : "s"}</td>
+      <td colspan="3">${g.legacy ? "&#9888; " : ""}${esc(g.label)} · ${rows.length} campaign${rows.length === 1 ? "" : "s"}</td>
       <td class="num">${fmt.money(t.daily_budget)}</td>
       <td class="num">${fmt.money(t.spend)}</td>
-      <td class="num">${fmt.money(t.spend_per_day)}</td>
       <td class="num">${fmt.int(t.trials)}</td>
       <td class="num ${cptTone(t.cpt_3d, target)}">${fmt.cpt(t.cpt_3d)}</td>
       <td class="num"></td>
       <td class="num">${fmt.int(t.paid)}</td>
-      <td class="num">${fmt.pct(t.trial_to_paid)}</td>
       <td class="num">${fmt.cpt(t.cost_per_paid)}</td>
       <td class="num">${fmt.int(t.platform_conversions)} · ${fmt.pct(t.ratio, 0)}</td>
     </tr>`;
@@ -308,27 +307,25 @@
       const open = state.open.has(c.id);
       const paused = c.status !== "ACTIVE";
+      const caveat = c.trials_3d < 3 ? `<div class="caveat">${c.trials_3d === 0 ? "0 trials in 3d" : `n=${c.trials_3d}: thin read`}</div>` : "";
       html += `<tr class="camp-row${c.legacy ? " legacy" : ""}${open ? " is-open" : ""}${paused ? " is-paused" : ""}" data-id="${esc(c.id)}" tabindex="0" aria-expanded="${open}">
         <td><span class="caret" aria-hidden="true">&#9656;</span> ${platformChip(c.platform)}</td>
-        <td><span class="strong">${esc(c.name)}</span>${c.legacy ? '<span class="tag legacy-tag">legacy</span>' : ""}<div class="small muted">${esc(c.type)} · ${esc(c.bid_strategy || "")}${c.start_date && c.start_date > d.window.start ? ` · live ${fmt.date(c.start_date)}` : ""}</div></td>
-        <td>${esc(c.country)}</td>
+        <td><span class="strong">${esc(c.name)}</span>${c.legacy ? '<span class="tag legacy-tag">legacy</span>' : ""}<div class="small muted">${esc(c.country)} · ${esc(c.type)} · ${esc(c.bid_strategy || "")}${c.start_date && c.start_date > d.window.start ? ` · live ${fmt.date(c.start_date)}` : ""}</div></td>
         <td>${badge(c.status)}</td>
         <td class="num">${fmt.money(c.daily_budget)}</td>
-        <td class="num">${fmt.money(c.spend)}</td>
-        <td class="num" title="${c.active_days} live day${c.active_days === 1 ? "" : "s"} in window">${fmt.money(c.spend_per_day)}</td>
+        <td class="num" title="${fmt.money(c.spend_per_day)} per live day across ${c.active_days} live day${c.active_days === 1 ? "" : "s"} in this window">${fmt.money(c.spend)}</td>
         <td class="num">${fmt.int(c.trials)}</td>
-        <td class="num monitor ${cptTone(c.cpt_3d, target)}" title="${fmt.money(c.spend_3d)} / ${c.trials_3d} trials, last 3 days">${fmt.cpt(c.cpt_3d)}</td>
+        <td class="num monitor ${cptTone(c.cpt_3d, target)}" title="${fmt.money(c.spend_3d)} / ${c.trials_3d} trials, last 3 days">${fmt.cpt(c.cpt_3d)}${caveat}</td>
         <td class="num ${cptTone(c.cpt_7d, target)}">${fmt.cpt(c.cpt_7d)}</td>
-        <td class="num">${fmt.int(c.paid)}</td>
-        <td class="num">${fmt.pct(c.trial_to_paid)}</td>
+        <td class="num" title="Trial to paid: ${fmt.pct(c.trial_to_paid)}. Recent cohorts are still maturing.">${fmt.int(c.paid)}</td>
         <td class="num">${fmt.cpt(c.cost_per_paid)}</td>
         <td class="num" title="${fmt.int(c.platform_conversions)} platform-reported conversions vs ${c.trials} PostHog trials"><span class="muted">${fmt.int(c.platform_conversions)} ·</span> ${ratioCell(c, band)}</td>
       </tr>`;
@@ -336,7 +333,7 @@
     });
   });
-  $("#camp-body").innerHTML = html || `<tr><td colspan="14" class="table-empty">No campaigns.</td></tr>`;
+  $("#camp-body").innerHTML = html || `<tr><td colspan="11" class="table-empty">No campaigns.</td></tr>`;
@@ -345,9 +342,9 @@
 
 function adsetRows(c, target) {
-  if (!c.adsets.length) return `<tr class="adset-row"><td></td><td colspan="13" class="muted">No ad sets.</td></tr>`;
+  if (!c.adsets.length) return `<tr class="adset-row"><td></td><td colspan="10" class="muted">No ad sets.</td></tr>`;
   const kind = c.adsets[0].kind || "ad set";
-  let html = `<tr class="adset-row"><td></td><td colspan="13" class="small muted">${c.adsets.length} ${esc(kind)}${c.adsets.length === 1 ? "" : "s"} · window totals, estimated split by ${c.adsets[0].allocation === "budget_share" ? "ad set budget" : "even share (no ad group budgets)"}</td></tr>`;
+  let html = `<tr class="adset-row"><td></td><td colspan="10" class="small muted">${c.adsets.length} ${esc(kind)}${c.adsets.length === 1 ? "" : "s"} · window totals, estimated split by ${c.adsets[0].allocation === "budget_share" ? "ad set budget" : "even share (no ad group budgets)"}</td></tr>`;
   c.adsets.forEach((a) => {
@@ -356,17 +353,14 @@
       <td></td>
       <td class="adset-name"><span>${esc(a.name)}</span><div class="small muted truncate" title="${esc(a.targeting || "")}">${esc(a.targeting || "")}</div></td>
-      <td class="muted">${esc(kind)}</td>
       <td>${badge(a.status)}</td>
       <td class="num">${a.daily_budget ? fmt.money(a.daily_budget) : fmt.none}</td>
-      <td class="num">${fmt.money(a.spend)}</td>
-      <td class="num muted">${fmt.pct(a.share_pct, 0)}</td>
+      <td class="num" title="${fmt.pct(a.share_pct, 0)} apportioned share">${fmt.money(a.spend)}</td>
       <td class="num">${fmt.int(a.trials)}</td>
       <td class="num"></td>
       <td class="num"></td>
       <td class="num">${fmt.int(a.paid)}</td>
-      <td class="num">${fmt.pct(a.trial_to_paid)}</td>
       <td class="num">${fmt.cpt(a.cost_per_paid)}</td>
       <td class="num ${cptTone(a.cost_per_trial, target)}" title="Window cost per trial">${fmt.cpt(a.cost_per_trial)} / trial</td>
@@ -410,5 +404,19 @@
   });
 }
 
+/* Put the operational monitor before exploratory charts; retain DOM/tab order. */
+(function orderSections() {
+  const table = $("#table-title").closest("section");
+  const funnel = $("#funnel-title").closest("section");
+  const daily = $("#daily-title").closest("section");
+  if (!table || !funnel || !daily) return;
+  const main = table.parentNode;
+  main.insertBefore(table, daily);
+  main.appendChild(funnel);
+})();
+
 wire();
 load(state.window);
```

### `templates/calendar.html` — unified diff

```diff
--- a/templates/calendar.html
+++ b/templates/calendar.html
@@ -74,6 +74,9 @@
   @media (max-width: 720px) {
+    #upcoming-card { order: -1; }
+    #cal-actions .action-controls { width: 100%; justify-content: flex-start; }
     .board { grid-template-columns: minmax(0, 1fr); }
@@ -157,6 +160,14 @@
 </section>
 
+<section class="card" id="cal-actions" aria-labelledby="cal-actions-title">
+  <div class="card-head">
+    <h2 class="card-title" id="cal-actions-title">Needs action</h2>
+    <span class="card-sub" id="cal-action-sub">Overdue, final approvals and Vin feedback</span>
+  </div>
+  <div id="cal-action-list"><div class="card-body"><div class="skeleton" style="height:64px"></div></div></div>
+</section>
+
 <section id="views">
@@ -188,7 +199,7 @@
-      <section class="card">
+      <section class="card" id="upcoming-card">
         <div class="card-head"><h2 class="card-title">Next 14 days</h2><span class="card-sub" id="upcoming-range"></span></div>
@@ -202,7 +213,7 @@
 <section class="card" id="tests-card">
-  <div class="card-head"><h2 class="card-title">Tests</h2><span class="card-sub">Benchmark, progress to the minimum read, and today's verdict</span></div>
+  <div class="card-head"><h2 class="card-title">Test schedule context</h2><a class="card-sub" href="/management#mg-tests">Full scoreboard and win/loss ledger in Management →</a></div>
```

### `static/js/calendar.js` — unified diff

```diff
--- a/static/js/calendar.js
+++ b/static/js/calendar.js
@@ -22,6 +22,7 @@
   }
   renderSummary();
+  renderActionQueue();
   renderBoard();
@@ -37,6 +38,60 @@
   $("#cal-summary").innerHTML = `${ov}<b>${c.by_status.running}</b> running · <b>${c.by_status.pending_feedback}</b> waiting on Vin · <b>${c.by_status.final_pending_approval}</b> awaiting approval · <b>${c.tests_running}</b> tests live`;
 }
 
+function renderActionQueue() {
+  const actions = [];
+  const seen = new Set();
+  data.overdue.forEach((item) => {
+    seen.add(item.id);
+    actions.push({ item, kind: "Overdue", tone: "bad", approve: false });
+  });
+  data.content.filter((item) => item.status === "final_pending_approval" && !seen.has(item.id)).forEach((item) => {
+    seen.add(item.id);
+    actions.push({ item, kind: "Final approval", tone: "watch", approve: true });
+  });
+  data.content.filter((item) => item.status === "pending_feedback" && !seen.has(item.id)).forEach((item) => {
+    actions.push({ item, kind: "Vin feedback", tone: "watch", approve: false });
+  });
+  $("#cal-action-sub").textContent = `${data.overdue.length} overdue · ${data.counts.by_status.final_pending_approval} final approval${data.counts.by_status.final_pending_approval === 1 ? "" : "s"} · ${data.counts.by_status.pending_feedback} feedback`;
+  if (!actions.length) {
+    $("#cal-action-list").innerHTML = `<div class="action-empty">Nothing overdue or waiting for review. Use the board to inspect scheduled and running work.</div>`;
+    return;
+  }
+  $("#cal-action-list").innerHTML = `<ul class="action-list">${actions.slice(0, 8).map(({ item, kind, tone, approve }) => `
+    <li class="action-item">
+      ${badge(tone, kind)}
+      <div class="action-copy">
+        <div class="action-title">${platformChip(item.platform)} ${esc(item.name)}</div>
+        <div class="action-meta">${esc(item.owner)} · due ${fmt.date(item.due)} · ${esc(item.format)} / ${esc(item.segment)}${item.campaign_name ? ` · ${esc(item.campaign_name)}` : ""}</div>
+      </div>
+      <div class="action-controls">
+        ${approve ? `<button class="btn btn-sm btn-primary" type="button" data-cal-approve="${esc(item.id)}">Approve</button>` : ""}
+        <button class="btn btn-sm" type="button" data-cal-open="${esc(item.id)}">Open on board</button>
+      </div>
+    </li>`).join("")}</ul>`;
+}
+
+$("#cal-actions").addEventListener("click", async (event) => {
+  const approve = event.target.closest("[data-cal-approve]");
+  if (approve) {
+    await moveItem(approve.dataset.calApprove, "approved", approve);
+    return;
+  }
+  const open = event.target.closest("[data-cal-open]");
+  if (!open) return;
+  tabsCtl.select("board");
+  const card = $(`.ccard[data-id="${CSS.escape(open.dataset.calOpen)}"]`);
+  if (card) {
+    card.scrollIntoView({ block: "center", behavior: "smooth" });
+    const edit = card.querySelector("[data-edit]");
+    if (edit) edit.focus({ preventScroll: true });
+  }
+});
+
 // ------------------------------------------------------------------ board
```

### `templates/reporting.html` — unified diff

```diff
--- a/templates/reporting.html
+++ b/templates/reporting.html
@@ -78,7 +78,7 @@
     body { background: #fff; font-size: 11px; display: block; min-height: 0; }
-    .topbar, .footer, .page-actions, .toast-stack { display: none !important; }
+    .sidebar, .footer, .page-actions, .toast-stack, .theme-toggle { display: none !important; }
@@ -111,7 +111,7 @@
 <section class="grid kpi-grid rp-kpis" id="rp-kpis" aria-label="Headline numbers">
-  {% for i in range(8) %}<div class="kpi"><div class="skeleton" style="height:58px"></div></div>{% endfor %}
+  {% for i in range(4) %}<div class="kpi"><div class="skeleton" style="height:58px"></div></div>{% endfor %}
 </section>
```

### `static/js/reporting.js` — unified diff

```diff
--- a/static/js/reporting.js
+++ b/static/js/reporting.js
@@ -45,47 +45,35 @@
 function renderKpis(d) {
   const k = d.kpis, tgt = d.cpa_target;
   const vsMonth = `vs ${range(k.prior_window)}`;
+  const thin = k.cpt_7d.trials < 3 ? ` · <span class="caveat">thin read</span>` : "";
   const html = [
+    tile({ label: "Cost / PostHog trial (7d)", value: fmt.cpt(k.cpt_7d.value), tone: cptTone(k.cpt_7d.value, tgt),
+      title: `${fmt.money(k.cpt_7d.spend)} / ${k.cpt_7d.trials} trials, ${range(d.kpis.w7_window)}`,
+      sub: `${deltaHtml(k.cpt_7d.delta, { goodWhen: "down", vs: `vs prior 7d (${fmt.cpt(k.cpt_7d.prev)})` })}<br><span class="muted">n=${fmt.int(k.cpt_7d.trials)} trials${thin}</span>` }),
+    tile({ label: "PostHog trials (MTD)", value: fmt.int(k.trials_mtd.value),
+      sub: deltaHtml(k.trials_mtd.delta, { goodWhen: "up", vs: vsMonth }) }),
     tile({ label: "Spend, month to date", value: fmt.money(k.mtd_spend.value),
       sub: deltaHtml(k.mtd_spend.delta, { goodWhen: "neutral", vs: vsMonth }) }),
-    tile({ label: "Projected month end", value: fmt.money(k.projected.value),
+    tile({ label: "Projected spend / budget", value: fmt.money(k.projected.value),
       tone: paceTone(k.projected.pace_pct), bar: k.projected.pace_pct,
       sub: `<span class="${paceTone(k.projected.pace_pct)} strong">${fmt.pct(k.projected.pace_pct)}</span> of ${fmt.moneyShort(k.projected.budget)} budget` }),
-    tile({ label: "Trials, month to date", value: fmt.int(k.trials_mtd.value),
-      sub: deltaHtml(k.trials_mtd.delta, { goodWhen: "up", vs: vsMonth }) }),
-    tile({ label: "Cost per trial, MTD", value: fmt.cpt(k.cpt_mtd.value), tone: cptTone(k.cpt_mtd.value, tgt),
-      sub: deltaHtml(k.cpt_mtd.delta, { goodWhen: "down", vs: vsMonth }) }),
-    tile({ label: "Cost per trial, last 7 days", value: fmt.cpt(k.cpt_7d.value), tone: cptTone(k.cpt_7d.value, tgt),
-      title: `${fmt.money(k.cpt_7d.spend)} / ${k.cpt_7d.trials} trials, ${range(d.kpis.w7_window)}`,
-      sub: deltaHtml(k.cpt_7d.delta, { goodWhen: "down", vs: `vs prior 7d (${fmt.cpt(k.cpt_7d.prev)})` }) }),
-    tile({ label: "Paid memberships, MTD trials", value: fmt.int(k.paid_mtd.value),
-      title: "Paid is credited to the trial's signup date; November trials have not had time to convert yet.",
-      sub: `still maturing (${k.paid_mtd.lag_days}-day lag) · ${fmt.int(k.paid_mtd.paid_30d)} paid from last-30-day trials` }),
-    tile({ label: "Cost per paid (matured cohort)", value: fmt.cpt(k.cost_per_paid.value),
-      title: `Trials ${range(k.cohort_window)}: ${k.cost_per_paid.paid} paid of ${k.cost_per_paid.trials} trials`,
-      sub: deltaHtml(k.cost_per_paid.delta, { goodWhen: "down", vs: `trials ${range(k.cohort_window)}` }) }),
-    tile({ label: "Trial → paid (matured cohort)", value: fmt.pct(k.trial_to_paid.value),
-      sub: deltaHtml(k.trial_to_paid.delta, { goodWhen: "up", points: true, vs: `vs ${range(k.cohort_prior_window)}` }) }),
   ];
@@ -248,4 +236,15 @@
 $("#rp-export").addEventListener("click", () => toast("CSV export downloading", "info"));
 
+/* Exceptions immediately follow the headline read; matured paid economics stay
+   beside their cohort explanation in the account table. */
+(function prioritizeChanges() {
+  const kpis = $("#rp-kpis");
+  const pacing = $("#rp-pace-title").closest("section");
+  const changes = $("#rp-chg-title").closest("section");
+  if (kpis && pacing && changes) pacing.parentNode.insertBefore(changes, pacing);
+})();
+
 load();
```

---

## 4. What I deliberately did not change

- **No Python, route, schema or seed changes.** The new queues and controls are composed entirely from existing responses and mutations.
- **PostHog remains the trial source of truth.** I did not blend platform conversions into CPT or silently “repair” Meta’s under-counting.
- **No fabricated ad-set precision.** Apportioned ad-set figures remain labelled as estimates. I did not turn them into exact performance readings.
- **No automated pause/scale engine.** The existing Management read supplies evidence; a person still initiates the mutation. A thin campaign should not be auto-paused because of a noisy CPT.
- **No universal `+10%` recommendation.** The direct scale control appears only where the existing API already classifies a campaign as `scaling`.
- **No new test verdict model.** Calendar and Management retain their current benchmark calculations. I changed hierarchy and navigation, not the meaning of a win or loss.
- **No replacement of tables with tiles everywhere.** Operational comparisons stay tabular; tiles are limited to headline reads. Charts remain explanatory rather than decorative KPI substitutes.
- **No drag-and-drop dependency.** Calendar movement still has buttons and a status select, so touch and keyboard users retain complete workflows.
- **No hiding of paid-lag or sample-data caveats.** Matured paid metrics remain available, but their caveats sit next to the numbers rather than dominating the headline row.
- **No removal of the activity log, CSV export, print view, adapter disclosure or legacy-campaign grouping.** These are operationally useful even when they are not primary above-the-fold content.