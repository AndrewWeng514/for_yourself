# Vditor (vendored)

- **Version:** 4.0.1
- **Source:** [Vanessa219/vditor](https://github.com/Vanessa219/vditor) — npm package `vditor@4.0.1`, `dist/` copied to this directory.
- **License:** See [LICENSE](./LICENSE) (MIT).

## Trimmed for 红利手账

Only files required for diary IR mode (Chinese UI, Ant Design icons, GitHub code highlight theme) are kept:

| Path | Purpose |
|------|---------|
| `dist/index.min.js`, `dist/index.css`, `dist/method.min.js` | Editor bundle |
| `dist/images/**` | Emoji, logo, loading assets |
| `dist/js/lute/**` | Markdown engine |
| `dist/js/highlight.js/highlight.min.js`, `third-languages.js` | Syntax highlighting |
| `dist/js/highlight.js/styles/github.min.css` | Preview code block theme |
| `dist/js/i18n/zh_CN.js` | UI strings |
| `dist/js/icons/ant.js` | Toolbar icons |
| `dist/css/content-theme/light.css` | Preview content theme |

Removed: other highlight.js themes (~250 CSS files), unused i18n locales, `material.js` icon set.

Loaded lazily from `web/js/diary.js` when the diary tab first needs the editor (not on initial page load).
