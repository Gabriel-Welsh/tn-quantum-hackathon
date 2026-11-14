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

async function loadPlants() {
  const response = await fetch("api/plants");
  if (!response.ok) throw new Error("Could not load plants.csv");
  const rows = await response.json();
  cards.replaceChildren();
  for (const row of rows) addCard(row);
}

document.querySelector("#add-plant").addEventListener("click", () => addCard({}, true));

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
