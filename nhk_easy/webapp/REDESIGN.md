# NHK Easy Reader - UI Redesign Plan

Full UI redesign of the local web reader. Persisted so it survives context loss.

## Decisions (confirmed with user)

- **Visual style**: modern magazine / card grid. Bold titles, image cards, genre badges.
- **Theme**: follow system (`prefers-color-scheme`) + manual toggle, persisted in localStorage.
- **Convenience features** (all four):
  1. Furigana toggle (show/hide `<rt>`), persisted, shortcut `f`.
  2. Font size / line-height control, persisted, shortcuts `+` / `-` / `0`.
  3. List search / filter (client-side, title match, URL `?q=` sync), shortcut `/`.
  4. Reading progress bar (detail) + read/unread marks (list), via localStorage.

## Constraints

- Zero build step. Vanilla CSS + JS only. No external fonts/CDN (offline-friendly local reader).
- Follow Vercel Web Interface Guidelines: a11y (aria-label, focus-visible, semantic HTML,
  skip link), `prefers-reduced-motion`, compositor-only animations, `color-scheme`,
  `theme-color`, no `user-scalable=no`, empty states, content truncation.
- Mobile-first responsive.

## Architecture changes

- New `nhk_easy/webapp/static/` with `app.css` + `app.js`; mount via `StaticFiles` in `app.py`.
- Inline head bootstrap script sets `data-theme` / `--font-scale` / `data-furigana`
  before paint (no FOUC); `app.js` (deferred) wires toggles, shortcuts, search, progress, read marks.
- `app.py` list route passes `image_ids` set so cards can show thumbnails.

## Files

- `static/app.css`     - design tokens, light/dark, card grid, reader, components, responsive
- `static/app.js`      - theme, furigana, font scale, search, read marks, progress, audio loop, shortcuts, help overlay
- `templates/base.html`   - head, tokens bootstrap, header toolbar, skip link, shortcut help overlay
- `templates/list.html`   - search box + card grid + empty state
- `templates/detail.html` - reading view + progress bar + restyled audio loop control
- `app.py`             - mount StaticFiles, pass image_ids

## Iteration 2 (verified against the real DB)

- **Card thumbnails**: every card always renders `<img src="/image/{news_id}">` plus a
  letter placeholder behind it. `app.js` adds `is-loaded` on load and removes the img on
  error, so cards show the real photo where one was downloaded and fall back otherwise.
  Removed the per-request `image_ids` glob (was 679 filesystem globs per list render).
- **Audio player**: replaced native `<audio controls>` with **Plyr 3.8.4**, self-hosted in
  `static/vendor/` (plyr.min.js + plyr.css + plyr.svg, no CDN). Themed via `--plyr-color-main`.
  The repeat-N-times loop is layered on top via the media element's `ended`/`play` events.
  Plyr keyboard is `focused`-only; our global shortcuts drive it (Space / , . / [ ]).
  Native `<audio>` hidden only under `html.js` (progressive enhancement fallback).
- **Performance**: `.card` uses `content-visibility: auto; contain-intrinsic-size: auto 340px`
  for the 600+ article grid (forced-layout cost measured ~10x lower).
- **Cache-busting**: static asset URLs carry `?v={{ static_v }}` (mtime-based) so clients
  pick up CSS/JS changes after a redeploy.

## Keyboard shortcuts

Global: `?` help, `t` theme, `f` furigana, `+`/`-` font, `0` reset font.
List: `/` focus search, `j`/`k` prev/next card, `Enter`/`o` open, `Esc` clear/blur.
Detail: `Space` play/pause, `,`/`.` seek -/+5s, `u`/`Esc` back to list.
(Shortcuts ignored while typing in an input.)
