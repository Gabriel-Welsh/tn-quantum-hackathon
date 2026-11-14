const DEFAULT_PLANTS = [
  {
    "plant_id": "COAL",
    "type": "coal steam",
    "pmin_mw": "140",
    "pmax_mw": "350",
    "marginal_cost_per_mwh": "21.69",
    "no_load_cost_per_h": "546",
    "startup_cost": "36750",
    "min_up_h": "24",
    "min_down_h": "48",
    "ramp_mw_per_h": "240",
    "on_at_start": "1",
    "rts_gen_uid": "123_STEAM_3",
    "scale": "1.0"
  },
  {
    "plant_id": "GAS_CC",
    "type": "gas combined cycle",
    "pmin_mw": "168",
    "pmax_mw": "350",
    "marginal_cost_per_mwh": "26.84",
    "no_load_cost_per_h": "206",
    "startup_cost": "27650",
    "min_up_h": "8",
    "min_down_h": "5",
    "ramp_mw_per_h": "245",
    "on_at_start": "0",
    "rts_gen_uid": "107_CC_1",
    "scale": "0.986"
  },
  {
    "plant_id": "PEAKER_A",
    "type": "gas combustion turbine",
    "pmin_mw": "20",
    "pmax_mw": "50",
    "marginal_cost_per_mwh": "28.89",
    "no_load_cost_per_h": "443",
    "startup_cost": "5150",
    "min_up_h": "3",
    "min_down_h": "3",
    "ramp_mw_per_h": "202",
    "on_at_start": "0",
    "rts_gen_uid": "113_CT_1",
    "scale": "0.909"
  },
  {
    "plant_id": "PEAKER_B",
    "type": "gas combustion turbine (older)",
    "pmin_mw": "20",
    "pmax_mw": "50",
    "marginal_cost_per_mwh": "39.51",
    "no_load_cost_per_h": "749",
    "startup_cost": "5150",
    "min_up_h": "3",
    "min_down_h": "3",
    "ramp_mw_per_h": "202",
    "on_at_start": "0",
    "rts_gen_uid": "223_CT_4",
    "scale": "0.909"
  },
  {
    "plant_id": "OIL",
    "type": "oil combustion turbine",
    "pmin_mw": "20",
    "pmax_mw": "50",
    "marginal_cost_per_mwh": "101.02",
    "no_load_cost_per_h": "694",
    "startup_cost": "130",
    "min_up_h": "1",
    "min_down_h": "1",
    "ramp_mw_per_h": "450",
    "on_at_start": "0",
    "rts_gen_uid": "101_CT_1",
    "scale": "2.5"
  },
  {
    "plant_id": "COAL_MID",
    "type": "coal steam (mid size)",
    "pmin_mw": "60",
    "pmax_mw": "150",
    "marginal_cost_per_mwh": "21.68",
    "no_load_cost_per_h": "378",
    "startup_cost": "22050",
    "min_up_h": "8",
    "min_down_h": "8",
    "ramp_mw_per_h": "174",
    "on_at_start": "1",
    "rts_gen_uid": "116_STEAM_1",
    "scale": "0.968"
  },
  {
    "plant_id": "COAL_SMALL",
    "type": "coal steam (small)",
    "pmin_mw": "39",
    "pmax_mw": "100",
    "marginal_cost_per_mwh": "23.8",
    "no_load_cost_per_h": "145",
    "startup_cost": "14700",
    "min_up_h": "8",
    "min_down_h": "4",
    "ramp_mw_per_h": "158",
    "on_at_start": "0",
    "rts_gen_uid": "201_STEAM_3",
    "scale": "1.316"
  },
  {
    "plant_id": "GAS_CC_2",
    "type": "gas combined cycle",
    "pmin_mw": "144",
    "pmax_mw": "300",
    "marginal_cost_per_mwh": "28.59",
    "no_load_cost_per_h": "262",
    "startup_cost": "23700",
    "min_up_h": "8",
    "min_down_h": "5",
    "ramp_mw_per_h": "210",
    "on_at_start": "0",
    "rts_gen_uid": "213_CC_3",
    "scale": "0.845"
  },
  {
    "plant_id": "PEAKER_C",
    "type": "gas combustion turbine",
    "pmin_mw": "20",
    "pmax_mw": "50",
    "marginal_cost_per_mwh": "25.91",
    "no_load_cost_per_h": "420",
    "startup_cost": "5150",
    "min_up_h": "3",
    "min_down_h": "3",
    "ramp_mw_per_h": "202",
    "on_at_start": "0",
    "rts_gen_uid": "322_CT_5",
    "scale": "0.909"
  },
  {
    "plant_id": "OIL_2",
    "type": "oil combustion turbine",
    "pmin_mw": "20",
    "pmax_mw": "50",
    "marginal_cost_per_mwh": "101.02",
    "no_load_cost_per_h": "694",
    "startup_cost": "130",
    "min_up_h": "1",
    "min_down_h": "1",
    "ramp_mw_per_h": "450",
    "on_at_start": "0",
    "rts_gen_uid": "101_CT_2",
    "scale": "2.5"
  }
];

const form = document.querySelector("#plants-form");
const cards = document.querySelector("#plant-cards");
const status = document.querySelector("#plants-status");

// To expose another plants.csv column, add its label and input type here,
// then add validation for it in server.py.
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

function showPlants(rows) {
  cards.replaceChildren();
  for (const row of rows) addCard(row);
}

async function loadPlants() {
  const response = await fetch("api/plants");
  if (!response.ok) throw new Error("Could not load plants.csv");
  showPlants(await response.json());
}

function parsePlantCsv(text) {
  const rows = [];
  let row = [];
  let value = "";
  let quoted = false;
  text = text.replace(/^\uFEFF/, "");

  for (let i = 0; i < text.length; i++) {
    const character = text[i];
    if (quoted) {
      if (character === '"' && text[i + 1] === '"') {
        value += '"';
        i++;
      } else if (character === '"') {
        quoted = false;
      } else {
        value += character;
      }
    } else if (character === '"' && value === "") {
      quoted = true;
    } else if (character === '"') {
      throw new Error("Invalid quote in CSV file.");
    } else if (character === ",") {
      row.push(value);
      value = "";
    } else if (character === "\n" || character === "\r") {
      row.push(value);
      if (row.some((cell) => cell.trim() !== "")) rows.push(row);
      row = [];
      value = "";
      if (character === "\r" && text[i + 1] === "\n") i++;
    } else {
      value += character;
    }
  }
  if (quoted) throw new Error("Unclosed quote in CSV file.");
  row.push(value);
  if (row.some((cell) => cell.trim() !== "")) rows.push(row);

  const headers = rows.shift()?.map((cell) => cell.trim());
  const required = FIELDS.map((field) => field.key);
  if (!headers || headers.length !== required.length ||
      new Set(headers).size !== required.length ||
      !required.every((key) => headers.includes(key))) {
    throw new Error("CSV columns must match plants.csv (the order may differ).");
  }
  if (!rows.length) throw new Error("The CSV file has no plants.");

  const plantIds = new Set();
  return rows.map((cells, index) => {
    const line = index + 2;
    if (cells.length !== headers.length) {
      throw new Error(`Row ${line} has ${cells.length} columns; expected ${headers.length}.`);
    }
    const plant = Object.fromEntries(headers.map((key, i) => [key, cells[i].trim()]));
    if (!plant.plant_id || !plant.type) {
      throw new Error(`Row ${line} needs a plant ID and type.`);
    }
    if (plantIds.has(plant.plant_id)) {
      throw new Error(`Repeated plant ID: ${plant.plant_id}.`);
    }
    plantIds.add(plant.plant_id);
    for (const field of FIELDS.filter((item) => item.type === "number" || item.type === "select")) {
      const raw = plant[field.key];
      const number = Number(raw);
      if (raw === "" || !Number.isFinite(number) || number < 0 ||
          (["min_up_h", "min_down_h", "on_at_start"].includes(field.key) && !Number.isInteger(number))) {
        throw new Error(`Row ${line}: invalid ${field.key}.`);
      }
    }
    if (Number(plant.pmax_mw) <= 0 || Number(plant.pmin_mw) > Number(plant.pmax_mw) ||
        Number(plant.scale) <= 0 || !["0", "1"].includes(plant.on_at_start)) {
      throw new Error(`Row ${line}: invalid output range, scale, or starting state.`);
    }
    return plant;
  });
}

document.querySelector("#load-default-plants").addEventListener("click", () => {
  showPlants(DEFAULT_PLANTS);
  status.textContent = "Loaded 10 default plants. Review them, then save.";
});

const csvInput = document.querySelector("#plant-csv-file");
const dropZone = document.querySelector("#plant-csv-drop-zone");

async function importPlantFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".csv")) {
    status.textContent = "Choose a .csv file.";
    return;
  }
  try {
    const rows = parsePlantCsv(await file.text());
    showPlants(rows);
    status.textContent = `Loaded ${rows.length} plants from ${file.name}. Review them, then save.`;
  } catch (error) {
    status.textContent = `Import failed: ${error.message}`;
  }
}

csvInput.addEventListener("change", () => {
  importPlantFile(csvInput.files[0]);
  csvInput.value = "";
});
for (const eventName of ["dragenter", "dragover"]) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("drag-over");
  });
}
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("drag-over");
  importPlantFile(event.dataTransfer.files[0]);
});

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

loadPlants().catch((error) => { status.textContent = error.message; });
