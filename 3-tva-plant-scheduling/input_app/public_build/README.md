# input_app/public_build

A static, server-free copy of the web app for public hosting (for example GitHub Pages) or opening straight from disk (`file://`). It has the same pages as `../index.html` but needs no `server.py`, so saving CSVs and running server-side algorithms aren't available here.

| File | What it is |
|---|---|
| `index.html` | The page shell (title "Power plant scheduling · public demo") |
| `app.js` | All page logic in one deferred script: plant cards, demand editor, CSV parsing, schedule and report charts |
| `styles.css` | Styles |

For the full local app, see [`../README.md`](../README.md).
