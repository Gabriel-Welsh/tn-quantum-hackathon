# Public power plant scheduling demo

This folder is a complete, static website. Keep **only these four files** together:

| File | Purpose |
| --- | --- |
| `index.html` | Accessible page structure and content |
| `styles.css` | Responsive light and dark styling |
| `app.js` | Example data, CSV import/export, browser storage, scheduling rules, and charts |
| `README.md` | Setup and maintenance instructions |

There are no dependencies, build commands, API keys, external fonts, or network calls. The site can open directly from `index.html`. Browser storage may be limited for `file://` pages, so use a web server when audience edits should persist.

## Host on GitHub Pages

The simplest setup is a **new public repository** containing `index.html`, `styles.css`, and `app.js` at its root. GitHub Pages does not publish an arbitrary `public_build/` subfolder using its basic branch setting.

1. Create a public GitHub repository for the demo.
2. Upload the three website files from this folder to the repository root. You may include this README.
3. Open **Settings → Pages**. Under **Build and deployment**, choose **Deploy from a branch**, then select `main` and `/ (root)`.
4. Wait for GitHub to show the site URL, then open that URL on a phone.
5. Make the QR code point to that HTTPS URL. Test it from a phone that is not signed in to GitHub.

GitHub Pages publishes a public site; do not add private data or credentials to this folder. Each visitor’s edits remain in their own browser and are not shared with other visitors.

## Run on your laptop

You need Python 3 and a copy of this `public_build` folder. Keep `index.html`, `styles.css`, and `app.js` together. There are no packages to install and no build step.

1. Open a terminal in the `public_build` folder. On Windows, you can open the folder in File Explorer, click its address bar, type `powershell`, and press Enter. On macOS or Linux, open Terminal and use `cd` to enter the folder.
2. Start the server with the command for your system:

   **Windows (PowerShell):**

   ```powershell
   py -m http.server 8000
   ```

   **macOS or Linux (Terminal):**

   ```sh
   python3 -m http.server 8000
   ```

   If the command says Python is missing, install Python 3 from [python.org](https://www.python.org/downloads/) and run it again. If port 8000 is already in use, replace `8000` in the command and URL with another port, such as `8765`.
3. On the same laptop, open **http://localhost:8000/** in a browser. The page should show the power plant scheduling demo. Leave the terminal open while testing; press **Ctrl+C** there to stop the server.

The site also opens by double-clicking `index.html`, but using the server is recommended because browser storage can be limited for `file://` pages. Your edits are stored in that browser on that laptop; they are not sent to the server.

### Open it on a phone on the same Wi-Fi

Start the server with `--bind 0.0.0.0` added to the command above. Find the laptop's local IPv4 address (`ipconfig` on Windows; your network settings on macOS or Linux). On the phone, open `http://LAPTOP-IP:8000/`, replacing `LAPTOP-IP` with that address. Allow Python through the laptop's firewall for the private network if prompted.

Keep the terminal open and the laptop awake. Some Wi-Fi networks block connections between devices; test on the actual network before sharing a QR code. A laptop server is available only while the laptop is running and reachable. For a public link that works anywhere, use the GitHub Pages instructions above.

## What visitors can do

- Edit up to 40 plants, import and download plant CSVs, and restore the ten-plant example.
- Change 24 hourly demand values and one reserve percentage.
- Generate a schedule with **Stable heuristic** or **Cheapest-first**.
- Inspect an accessible chart and exact-value table for each schedule.
- See two published local HiGHS benchmark charts, each backed by a data table.

Plant and demand edits apply only after their **Apply** button is pressed. Applied data is saved in this browser’s local storage where available. The **Generate schedule** button uses the applied data. The site sends no edits to a server.

## Scientific scope

The public copy preserves the educational workflow of the Python app while running entirely in a browser. It **does not run** the original exact MILP, QAOA, or qBraid hardware jobs. The two scheduling rules are classical teaching examples. The cost is a simplified dispatch estimate; ramp limits are not checked. Results from edited data are not research results or an optimality claim. The two report charts show fixed, published local HiGHS medians and do not change with visitor inputs.

## Accessibility and maintenance

The site uses semantic headings, a skip link, native buttons and inputs, visible focus, live status text, reduced-motion support, and tables with captions and row/column headers. Charts have titles and descriptions, with the same data available in nearby tables. The navigation is a set of normal links, so browser history and copied URLs work. Test changes with keyboard-only navigation, a phone at 200% zoom, and a screen reader when available.

`app.js` includes the bundled example data and the measured report values so hosting needs no CSV or JSON assets. When the source examples change, update `EXAMPLE_PLANTS_CSV`, `EXAMPLE_DEMAND`, and `BENCHMARKS` in that file. Keep chart titles, descriptions, table headers, and the scientific-scope text in sync with any calculation changes.
