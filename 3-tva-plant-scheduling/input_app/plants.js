// Power plant editor for the #plants section of index.html. On load it fetches
// saved plants.csv through /api/plants. The default button and CSV import only
// replace the cards in the browser; the Save form POSTs the chosen rows to
// server.py. Keep these selectors aligned with the HTML IDs.
const form = document.querySelector("#plants-form");
const cards = document.querySelector("#plant-cards");
const status = document.querySelector("#plants-status");
const csvInput = document.querySelector("#plant-csv-file");
const dropZone = document.querySelector("#plant-csv-drop-zone");

// FIELDS drives both card controls and the values sent on Save. To expose a
// plants.csv column, add it here (the import header check reads this list),
// and validate/save it in server.py. The order also defines the card layout.
const FIELDS = [
  { key: "plant_id", label: "Plant ID", type: "text", required: true },
  { key: "type", label: "Plant type", type: "text", required: true },
  { key: "pmin_mw", label: "Minimum output (MW)", type: "number", min: 0, step: "any" },
  { key: "pmax_mw", label: "Maximum output (MW)", type: "number", min: 0, step: "any" },
  { key: "marginal_cost_per_mwh", label: "Marginal cost ($/MWh)", type: "number", min: 0, step: "any" },
  { key: "no_load_cost_per_h", label: "No-load cost ($/h)", type: "number", min: 0, step: "any" },
  { key: "startup_cost", label: "Startup cost ($)", type: "number", min: 0, step: "any" },
  { key: "min_up_h", label: "Minimum hours on", type: "number", min: 0, step: 1 },
  { key: "min_down_h", label: "Minimum hours off", type: "number", min: 0, step: 1 },
  { key: "ramp_mw_per_h", label: "Ramp (MW/h)", type: "number", min: 0, step: "any" },
  { key: "on_at_start", label: "On at start?", type: "select" },
  { key: "rts_gen_uid", label: "RTS generator ID (optional)", type: "text" },
  { key: "scale", label: "Scale", type: "number", min: 0, step: "any" },
];

// Snapshot of ../data/plants10.csv for the reset button. Keep it independent
// of editable plants.csv, or saving a custom fleet would replace the defaults.
// When the source example changes, update this literal and its header together.
const DEFAULT_PLANTS_CSV = `plant_id,type,pmin_mw,pmax_mw,marginal_cost_per_mwh,no_load_cost_per_h,startup_cost,min_up_h,min_down_h,ramp_mw_per_h,on_at_start,rts_gen_uid,scale
COAL,coal steam,140,350,21.69,546,36750,24,48,240,1,123_STEAM_3,1.0
GAS_CC,gas combined cycle,168,350,26.84,206,27650,8,5,245,0,107_CC_1,0.986
PEAKER_A,gas combustion turbine,20,50,28.89,443,5150,3,3,202,0,113_CT_1,0.909
PEAKER_B,gas combustion turbine (older),20,50,39.51,749,5150,3,3,202,0,223_CT_4,0.909
OIL,oil combustion turbine,20,50,101.02,694,130,1,1,450,0,101_CT_1,2.5
COAL_MID,coal steam (mid size),60,150,21.68,378,22050,8,8,174,1,116_STEAM_1,0.968
COAL_SMALL,coal steam (small),39,100,23.8,145,14700,8,4,158,0,201_STEAM_3,1.316
GAS_CC_2,gas combined cycle,144,300,28.59,262,23700,8,5,210,0,213_CC_3,0.845
PEAKER_C,gas combustion turbine,20,50,25.91,420,5150,3,3,202,0,322_CT_5,0.909
OIL_2,oil combustion turbine,20,50,101.02,694,130,1,1,450,0,101_CT_2,2.5`;

// Parse both the bundled default CSV and user uploads. This small parser
// supports quoted commas/newlines and doubled quotes; it accepts LF and CRLF.
// It checks the exact set of columns before cards are replaced, so a failed
// import leaves the current editor rows alone. server.py validates row values
// again when the user saves.
function parsePlantCsv(text) {
  const records = [];
  let record = [];
  let value = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { value += '"'; i++; }
      else if (quoted || value === "") quoted = !quoted;
      else throw new Error("Invalid CSV quote");
    } else if (char === "," && !quoted) {
      record.push(value);
      value = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[i + 1] === "\n") i++;
      record.push(value);
      if (record.some((cell) => cell !== "")) records.push(record);
      record = [];
      value = "";
    } else {
      value += char;
    }
  }
  if (quoted) throw new Error("Unclosed CSV quote");
  record.push(value);
  if (record.some((cell) => cell !== "")) records.push(record);
  // Header order may vary, but all editable plant fields must be present once.
  const header = records.shift();
  const columns = FIELDS.map((field) => field.key);
  if (!header || header.length !== columns.length ||
      new Set(header).size !== columns.length ||
      !columns.every((column) => header.includes(column))) {
    throw new Error("CSV columns must match plants.csv");
  }
  if (!records.length || records.some((row) => row.length !== header.length)) {
    throw new Error("CSV needs complete plant rows");
  }
  return records.map((row) => Object.fromEntries(header.map((key, index) => [key, row[index]])));
}

// Build one card from a CSV/API row. data-field attributes connect each input
// back to FIELDS in the Save handler; the heading follows edits to plant_id.
function addCard(row = {}, isNew = false) {
  const card = document.createElement("article");
  card.className = "plant-card";
  const heading = document.createElement("h2");
  heading.textContent = row.plant_id || "New power plant";
  card.append(heading);
  const fields = document.createElement("div");
  fields.className = "fields";

  for (const field of FIELDS) {
    const label = document.createElement("label");
    label.textContent = field.label;
    let control;
    // on_at_start is a 0/1 select; all other fields use HTML text/number inputs.
    if (field.type === "select") {
      control = document.createElement("select");
      for (const [value, text] of [["0", "No (0)"], ["1", "Yes (1)"]]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        control.append(option);
      }
      control.value = row[field.key] ?? "0";
    } else {
      control = document.createElement("input");
      control.type = field.type;
      control.required = field.required || field.type === "number";
      if (field.type === "number") {
        control.min = field.min;
        control.step = field.step;
      }
      control.value = row[field.key] ?? (field.key === "scale" ? "1" : "");
    }
    control.dataset.field = field.key;
    if (field.key === "plant_id") {
      control.addEventListener("input", () => {
        heading.textContent = control.value.trim() || "New power plant";
      });
    }
    label.append(control);
    fields.append(label);
  }
  card.append(fields);
  // The optional new-row controls are kept here for future manual-add UI.
  if (isNew) {
    const discard = document.createElement("button");
    discard.type = "button";
    discard.textContent = "Discard new plant";
    discard.addEventListener("click", () => card.remove());
    card.append(discard);
  }
  cards.append(card);
  if (isNew) card.querySelector('[data-field="plant_id"]').focus();
}

// Replace all cards after a successful fetch, reset, import, or Save reload.
function renderPlants(rows) {
  cards.replaceChildren();
  for (const row of rows) addCard(row);
}

// Read the persisted CSV through the server API. JSON values arrive as strings,
// which are suitable for input.value until the Save handler converts numbers.
async function loadPlants() {
  const response = await fetch("api/plants");
  if (!response.ok) throw new Error("Could not load plants.csv");
  renderPlants(await response.json());
}

// Reset the visible editor to the bundled example; this does not write disk.
document.querySelector("#load-default-plants").addEventListener("click", () => {
  renderPlants(parsePlantCsv(DEFAULT_PLANTS_CSV));
  status.textContent = "Loaded 10 default plants. Click Save plants.csv to keep them.";
});

// File.text() reads a selected or dropped CSV locally. Keep prior cards if
// parsing fails, and tell the user that a successful import still needs Save.
async function importPlantFile(file) {
  if (!file) return;
  try {
    const rows = parsePlantCsv(await file.text());
    renderPlants(rows);
    status.textContent = `Loaded ${rows.length} plants from ${file.name}. Click Save plants.csv to keep them.`;
  } catch (error) {
    status.textContent = `Import failed: ${error.message}`;
  }
}

// The label in index.html opens this hidden file input. Clearing its value
// allows selecting the same file again after edits or an import error.
csvInput.addEventListener("change", () => {
  importPlantFile(csvInput.files[0]);
  csvInput.value = "";
});
// Drag/drop uses the same import function as the file picker. Preventing the
// browser default keeps a dropped CSV from replacing the entire app page.
dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("drag-over");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("drag-over");
  importPlantFile(event.dataTransfer.files[0]);
});

// Gather every card in FIELDS order, convert numeric controls, then ask the
// server to validate and atomically replace plants.csv. Reload after success
// so cards reflect the exact rows saved; schedule runs use that saved file.
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const rows = [...cards.querySelectorAll(".plant-card")].map((card) => {
    const row = {};
    for (const field of FIELDS) {
      const control = card.querySelector(`[data-field="${field.key}"]`);
      row[field.key] = field.type === "number" || field.type === "select"
        ? Number(control.value) : control.value.trim();
    }
    return row;
  });
  status.textContent = "Saving…";
  try {
    const response = await fetch("api/plants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rows),
    });
    if (!response.ok) throw new Error(await response.text());
    await loadPlants();
    status.textContent = "Saved to input_app/plants.csv.";
  } catch (error) {
    status.textContent = `Save failed: ${error.message}`;
  }
});

// Show saved plants on first load. Keep fetch errors visible in the page.
loadPlants().catch((error) => { status.textContent = error.message; });
