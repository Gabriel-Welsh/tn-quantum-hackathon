# Generate the two report charts from measured CSVs. Run from input_app/:
#   Rscript hardware_report.R
# or pass both input paths:
#   Rscript hardware_report.R speed_results.csv hardware_results.csv
# Missing inputs leave their chart in the HTML placeholder state. Do not add
# synthetic example rows to the published CSVs or label simulator runs as QPU.
# See HARDWARE_REPORT_TEMPLATE.md for every column and measurement rule.

args <- commandArgs(trailingOnly = TRUE)
if (length(args) > 2L)
  stop("Usage: Rscript hardware_report.R [speed_results.csv] [hardware_results.csv]")
speed_file <- if (length(args) >= 1L) args[[1L]] else "speed_results.csv"
hardware_file <- if (length(args) >= 2L) args[[2L]] else "hardware_results.csv"

read_measurements <- function(path, columns) {
  data <- read.csv(path, colClasses = "character", check.names = FALSE,
                   strip.white = TRUE, na.strings = c("", "NA"))
  missing <- setdiff(columns, names(data))
  if (length(missing)) stop(sprintf("%s is missing: %s", path, paste(missing, collapse = ", ")))
  if (!nrow(data) || anyNA(data[columns])) stop(sprintf("%s needs complete measured rows", path))
  data
}

whole_number <- function(data, column, positive = FALSE) {
  value <- suppressWarnings(as.numeric(data[[column]]))
  if (any(!is.finite(value)) || any(value != floor(value)) ||
      any(value < if (positive) 1 else 0))
    stop(sprintf("%s must contain %swhole numbers", column, if (positive) "positive " else "nonnegative "))
  value
}

positive_number <- function(data, column) {
  value <- suppressWarnings(as.numeric(data[[column]]))
  if (any(!is.finite(value)) || any(value <= 0))
    stop(sprintf("%s must contain positive numbers", column))
  value
}

make_speed_chart <- function(path) {
  required <- c("case_id", "plants", "hours", "trial", "milp_seconds",
                "hybrid_seconds", "backend", "milp_valid", "hybrid_valid",
                "milp_cost", "hybrid_cost")
  data <- read_measurements(path, required)
  data$plants <- whole_number(data, "plants", positive = TRUE)
  data$hours <- whole_number(data, "hours", positive = TRUE)
  data$trial <- whole_number(data, "trial", positive = TRUE)
  data$milp_seconds <- positive_number(data, "milp_seconds")
  data$hybrid_seconds <- positive_number(data, "hybrid_seconds")
  data$milp_cost <- positive_number(data, "milp_cost")
  data$hybrid_cost <- positive_number(data, "hybrid_cost")
  if (any(tolower(data$milp_valid) != "true") || any(tolower(data$hybrid_valid) != "true"))
    stop("Only matched, valid schedules can appear in the runtime comparison")
  allowed <- c("local_simulator", "remote_simulator", "qpu")
  if (length(unique(data$backend)) != 1L || !data$backend[[1L]] %in% allowed)
    stop("Use one backend per speed chart: local_simulator, remote_simulator, or qpu")
  if (anyDuplicated(paste(data$case_id, data$trial, sep = "\r")))
    stop("Each case_id and trial pair must occur once")
  cases <- unique(data$case_id)
  if (length(cases) > 8L) stop("Use at most eight cases per chart for readable labels")
  for (id in cases) {
    group <- data[data$case_id == id, ]
    if (length(unique(group$plants)) != 1L || length(unique(group$hours)) != 1L)
      stop(sprintf("%s has inconsistent plant or hour counts", id))
  }
  samples <- lapply(cases, function(id) data[data$case_id == id, ])
  labels <- vapply(samples, function(group)
    sprintf("%s\n%s plants × %sh", group$case_id[[1L]], group$plants[[1L]], group$hours[[1L]]), "")
  medians <- rbind(
    MILP = vapply(samples, function(group) median(group$milp_seconds), 0.0),
    `QAOA–MILP` = vapply(samples, function(group) median(group$hybrid_seconds), 0.0)
  )
  lower <- rbind(
    vapply(samples, function(group) unname(quantile(group$milp_seconds, .25)), 0.0),
    vapply(samples, function(group) unname(quantile(group$hybrid_seconds, .25)), 0.0)
  )
  upper <- rbind(
    vapply(samples, function(group) unname(quantile(group$milp_seconds, .75)), 0.0),
    vapply(samples, function(group) unname(quantile(group$hybrid_seconds, .75)), 0.0)
  )
  grDevices::svg("runtime-comparison.svg", width = 11, height = 6, bg = "white")
  on.exit(grDevices::dev.off(), add = TRUE)
  par(mar = c(7, 5, 4, 1.5))
  mid <- barplot(medians, beside = TRUE, names.arg = labels, las = 2,
                 col = c("#287cb5", "#b94715"), border = NA,
                 ylim = c(0, max(upper) * 1.25), ylab = "End-to-end wall-clock seconds",
                 main = "MILP versus QAOA–MILP: measured runtime",
                 legend.text = rownames(medians),
                 args.legend = list(x = "topright", bty = "n"))
  for (i in seq_len(nrow(mid))) for (j in seq_len(ncol(mid)))
    arrows(mid[i, j], lower[i, j], mid[i, j], upper[i, j],
           angle = 90, code = 3, length = 0.04)
  mtext(sprintf("Bars: median; whiskers: interquartile range | backend: %s | matched valid trials",
                data$backend[[1L]]), side = 3, line = 0.2, cex = 0.75)
  message("Wrote runtime-comparison.svg from ", path)
}

make_qpu_chart <- function(path) {
  required <- c("device_type", "device_id", "job_id", "hour", "bitstring", "count", "shots")
  data <- read_measurements(path, required)
  if (length(unique(data$device_type)) != 1L || data$device_type[[1L]] != "qpu")
    stop("device_type must be qpu; verify the actual device and job outside this CSV")
  for (column in c("device_id", "job_id", "hour", "shots"))
    if (length(unique(data[[column]])) != 1L)
      stop(sprintf("One QPU job per chart: %s must be identical in every row", column))
  data$hour <- whole_number(data, "hour")
  data$count <- whole_number(data, "count")
  data$shots <- whole_number(data, "shots", positive = TRUE)
  if (!all(grepl("^[01]+$", data$bitstring)) ||
      length(unique(nchar(data$bitstring))) != 1L || anyDuplicated(data$bitstring))
    stop("bitstrings must be unique, binary, and have equal width with leading zeroes")
  if (sum(data$count) != data$shots[[1L]]) stop("Counts must sum to the job's shots")
  counts <- sort(setNames(data$count, data$bitstring), decreasing = TRUE)
  top <- head(counts, 20L)
  if (length(counts) > 20L) top <- c(top, "Other bitstrings" = sum(tail(counts, -20L)))
  grDevices::svg("hardware-histogram.svg", width = 11, height = 6, bg = "white")
  on.exit(grDevices::dev.off(), add = TRUE)
  par(mar = c(7.5, 5, 4, 1.5))
  barplot(top, las = 2, cex.names = 0.7, col = "#287cb5", border = NA,
          ylab = "Measured shots", main = "QAOA QPU measurement histogram")
  mtext(sprintf("%s | job %s | hour %s | %s shots", data$device_id[[1L]],
                data$job_id[[1L]], data$hour[[1L]], data$shots[[1L]]),
        side = 3, line = 0.3, cex = 0.7)
  message("Wrote hardware-histogram.svg from ", path)
}

if (file.exists(speed_file)) {
  make_speed_chart(speed_file)
} else {
  message("No speed CSV; leaving runtime graph as an empty template: ", speed_file)
}
if (file.exists(hardware_file)) {
  make_qpu_chart(hardware_file)
} else {
  message("No QPU CSV; leaving hardware graph as an empty template: ", hardware_file)
}
