# QAOA hardware report template. Run from input_app/:
#   Rscript hardware_report.R hardware_results.csv
#
# Supply a CSV exported from ONE actual QPU job (not a local or remote simulator).
# The CSV is not included here; do not present the page as a hardware result
# until the job ID, device ID, and measured counts have been verified.
# Required header, in any order:
#   device_type,device_id,job_id,hour,bitstring,count,shots
# Example format ONLY (replace every value with real QPU data):
#   qpu,<actual QPU device ID>,<actual job ID>,14,00000000,12,200
#   qpu,<same device ID>,<same job ID>,14,00000001,8,200
#   ...one row for each measured bitstring; counts across all rows must total 200.
#
# device_type: exactly "qpu"; this is a provenance label, not proof of hardware.
# device_id: qBraid device ID of the physical processor (not a simulator ID).
# job_id: qBraid job ID for the run. Use the same job ID in every row.
# hour: zero-based scheduling hour used to build the circuit; same in every row.
# bitstring: measured binary string as returned by the job, with all qubits and
#            leading zeroes preserved. Qiskit puts qubit 0 at the RIGHT end.
#            For the five-plant, three-slack-bit case it has eight digits;
#            the rightmost five encode plant commitments, the other three slack.
# count: nonnegative integer number of shots that measured this bitstring.
# shots: total shots requested for the job, repeated identically on each row.
#        The sum of count must equal shots. Zero-count bitstrings can be omitted.
#
# This first template draws a measured-bitstring histogram. Future graphs can
# be added after their definitions and input columns are agreed upon. The SVG
# is served by server.py at /hardware-histogram.svg and shown on the hardware
# report tab after a browser refresh. No R process runs inside the web server.

args <- commandArgs(trailingOnly = TRUE)
if (length(args) > 1L) stop("Usage: Rscript hardware_report.R [hardware_results.csv]")
input_file <- if (length(args) == 1L) args[[1L]] else "hardware_results.csv"
output_file <- "hardware-histogram.svg"
if (!file.exists(input_file)) stop(sprintf("CSV not found: %s", input_file))

results <- read.csv(input_file, stringsAsFactors = FALSE, check.names = FALSE,
                    strip.white = TRUE)
required <- c("device_type", "device_id", "job_id", "hour", "bitstring", "count", "shots")
missing <- setdiff(required, names(results))
if (length(missing)) stop(sprintf("Missing CSV columns: %s", paste(missing, collapse = ", ")))
if (nrow(results) == 0L || anyNA(results[required])) stop("CSV needs nonempty rows without missing fields")

for (field in c("device_type", "device_id", "job_id", "bitstring")) {
  results[[field]] <- trimws(as.character(results[[field]]))
  if (any(!nzchar(results[[field]]))) stop(sprintf("%s cannot be blank", field))
}
if (length(unique(results$device_type)) != 1L || unique(results$device_type) != "qpu")
  stop("device_type must be qpu for every row; simulator data belongs in a separate report")
for (field in c("device_id", "job_id", "hour", "shots")) {
  if (length(unique(results[[field]])) != 1L)
    stop(sprintf("One QPU job per CSV: %s must be identical in every row", field))
}
if (!all(grepl("^[01]+$", results$bitstring)) ||
    length(unique(nchar(results$bitstring))) != 1L ||
    anyDuplicated(results$bitstring))
  stop("bitstring must be unique, binary, and the same width in every row")
for (field in c("hour", "count", "shots")) {
  value <- suppressWarnings(as.numeric(results[[field]]))
  if (any(!is.finite(value)) || any(value < 0) || any(value != floor(value)))
    stop(sprintf("%s must contain nonnegative whole numbers", field))
  results[[field]] <- value
}
if (unique(results$shots) == 0 || sum(results$count) != unique(results$shots))
  stop("shot counts must add up to the positive shots value")

counts <- setNames(results$count, results$bitstring)
counts <- sort(counts, decreasing = TRUE)
top <- head(counts, 20L)
if (length(counts) > 20L) top <- c(top, "Other bitstrings" = sum(tail(counts, -20L)))

render_histogram <- function() {
  grDevices::svg(filename = output_file, width = 11, height = 6, bg = "white")
  on.exit(grDevices::dev.off(), add = TRUE)
  par(mar = c(7.5, 5, 4, 1.5))
  barplot(top, las = 2, cex.names = 0.7, col = "#287cb5", border = NA,
          ylab = "Measured shots", main = "QAOA QPU measurement histogram")
  mtext(sprintf("%s | job %s | hour %s | %s shots",
                results$device_id[[1L]], results$job_id[[1L]],
                results$hour[[1L]], results$shots[[1L]]),
        side = 3, line = 0.3, cex = 0.7)
}
render_histogram()
cat(sprintf("Wrote %s from %s\n", output_file, input_file))
