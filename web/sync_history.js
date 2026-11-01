"use strict";
const $ = (id) => document.getElementById(id),
  fmt = new Intl.NumberFormat("el-GR"),
  when = (value) =>
    value
      ? new Intl.DateTimeFormat("el-GR", {
          dateStyle: "medium",
          timeStyle: "short",
          timeZone: "Europe/Athens",
        }).format(new Date(value))
      : "—";
const statusLabels = {
    committed: "Ολοκληρώθηκε",
    failed: "Απέτυχε · χωρίς δημοσίευση",
    collecting: "Χωρίς τελική επιβεβαίωση",
    commit_unknown: "Άγνωστη έκβαση · χρειάζεται έλεγχος",
  },
  modes = {
    all: "Όλες οι πηγές",
    tee: "TEE",
    ktima: "Κτηματολόγιο",
    ydro: "ΕΜΣΥ",
  },
  kinds = {
    new: "Νέα εγγραφή",
    updated: "Τροποποίηση",
    removed: "Αφαίρεση",
    source_id: "Αλλαγή ID πηγής",
  };
let runOffset = 0,
  changeOffset = 0,
  runId = null,
  overviewSerial = 0,
  detailSerial = 0;
function el(tag, text, className) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
}
function message(text, error = false) {
  $("message").textContent = text;
  $("message").className = "notice" + (error ? " error" : "");
  $("message").hidden = !text;
}
async function get(path, params) {
  const response = await fetch(path + "?" + new URLSearchParams(params), {
    cache: "no-store",
  });
  const body = await response.json();
  if (!response.ok)
    throw Error(
      typeof body.detail === "string"
        ? body.detail
        : "Έλεγξε τις ημερομηνίες και τα φίλτρα.",
    );
  return body;
}
function pageButtons(prefix, offset, total) {
  $(prefix + "-prev").disabled = offset === 0;
  $(prefix + "-next").disabled = offset + 25 >= total;
  $(prefix + "-page").textContent = total
    ? `${offset + 1}–${Math.min(offset + 25, total)} από ${fmt.format(total)}`
    : "0 εγγραφές";
}
function resetView() {
  for (const k of ["new", "updated", "removed", "geometry"])
    $(k).textContent = "—";
  $("layers").replaceChildren();
  $("runs").replaceChildren();
  $("layers-empty").hidden = false;
  $("runs-empty").hidden = false;
  $("layers-empty").textContent = "Δεν υπάρχουν διαθέσιμα δεδομένα.";
  $("runs-empty").textContent = "Δεν υπάρχουν διαθέσιμες εκτελέσεις.";
  $("run-count").textContent = "";
  $("detail").hidden = true;
  pageButtons("runs", 0, 0);
}
async function loadOverview() {
  const serial = ++overviewSerial;
  $("refresh").disabled = true;
  message("");
  const params = {
    period: $("period").value,
    domain: $("domain").value,
    changed_only: $("changed").checked,
    offset: runOffset,
    limit: 25,
  };
  if (params.period === "custom") {
    params.start = $("start").value;
    params.end = $("end").value;
  }
  try {
    const data = await get("/sync-history/api/overview", params);
    if (serial !== overviewSerial) return;
    if (!data.installed) {
      resetView();
      $("tracking").textContent = "Δεν έχει ενεργοποιηθεί";
      message(
        data.message +
          " Εκτέλεσε το setup_sync_history.py --apply για την έναρξη.",
      );
      return;
    }
    $("tracking").textContent =
      "Καταγραφή από " + when(data.tracking_started_at);
    for (const k of ["new", "updated", "removed", "geometry"])
      $(k).textContent = fmt.format(data.totals[k]);
    const committed = data.counts.committed || 0,
      failed = data.counts.failed || 0,
      pending =
        (data.counts.collecting || 0) + (data.counts.commit_unknown || 0);
    $("coverage").textContent =
      `${committed} ολοκληρωμένες εκτελέσεις · ${failed} αποτυχημένες · ${pending} χωρίς τελική επιβεβαίωση. Η γεωμετρία περιλαμβάνεται στις τροποποιήσεις. Η ίδια εγγραφή μπορεί να αλλάξει σε πολλές εκτελέσεις. Αλλαγές μόνο του ID πηγής: ${data.totals.source_id}.`;
    $("layers").replaceChildren();
    for (const row of data.layers) {
      const tr = el("tr"),
        name = el("td", row.label);
      name.append(el("span", row.domain_label + " · " + row.table_name, "sub"));
      tr.append(name);
      for (const k of [
        "new",
        "updated",
        "removed",
        "geometry",
        "unique_records",
      ])
        tr.append(el("td", fmt.format(row[k]), "n " + k));
      $("layers").append(tr);
    }
    $("layers-empty").hidden = data.layers.length > 0;
    $("layers-empty").textContent = committed
      ? "Δεν βρέθηκαν αλλαγές για αυτά τα φίλτρα."
      : "Δεν έχει καταγραφεί ολοκληρωμένος συγχρονισμός στην περίοδο.";
    $("runs").replaceChildren();
    for (const run of data.runs) {
      const tr = el("tr"),
        dateCell = el("td"),
        button = el("button", when(run.started_at), "run-link");
      button.type = "button";
      button.onclick = () => openRun(run.id);
      dateCell.append(button);
      tr.append(dateCell, el("td", modes[run.mode]));
      const state = el("td");
      state.append(
        el("span", statusLabels[run.status], "status " + run.status),
      );
      if (run.error_message) state.append(el("span", run.error_message, "sub"));
      tr.append(
        state,
        el(
          "td",
          run.status === "committed"
            ? `+${run.new} / ~${run.updated} / −${run.removed}`
            : "—",
          "n",
        ),
      );
      $("runs").append(tr);
    }
    $("run-count").textContent = fmt.format(data.total_runs) + " εκτελέσεις";
    $("runs-empty").hidden = data.runs.length > 0;
    $("runs-empty").textContent = "Δεν υπάρχουν εκτελέσεις στην περίοδο.";
    pageButtons("runs", runOffset, data.total_runs);
    if (!data.total_runs)
      message(
        "Το ιστορικό είναι έτοιμο. Θα εμφανιστούν οι επόμενοι συγχρονισμοί που θα τρέξεις από το μενού.",
      );
    else if (pending)
      message(
        "Υπάρχει εκτέλεση χωρίς τελική επιβεβαίωση. Μπορεί να εκτελείται ακόμη ή να διακόπηκε· δεν περιλαμβάνεται στα σύνολα.",
      );
  } catch (error) {
    if (serial !== overviewSerial) return;
    resetView();
    $("tracking").textContent = "Μη διαθέσιμο";
    message(error.message, true);
  } finally {
    if (serial === overviewSerial) $("refresh").disabled = false;
  }
}
async function openRun(id) {
  runId = id;
  changeOffset = 0;
  $("kind").value = "";
  $("key").value = "";
  $("detail-table").replaceChildren(el("option", "Όλοι οι πίνακες"));
  $("detail-table").firstChild.value = "";
  $("detail").hidden = false;
  await loadDetails(true);
  $("detail").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function loadDetails(initialize = false) {
  if (!runId) return;
  const serial = ++detailSerial;
  const params = {
    table: $("detail-table").value,
    domain: $("domain").value,
    kind: $("kind").value,
    key: $("key").value,
    offset: changeOffset,
    limit: 25,
  };
  try {
    const data = await get(
      "/sync-history/api/runs/" + encodeURIComponent(runId),
      params,
    );
    if (serial !== detailSerial) return;
    $("detail-title").textContent =
      when(data.run.started_at) +
      " · " +
      modes[data.run.mode] +
      " · " +
      statusLabels[data.run.status];
    if (initialize) {
      for (const layer of data.layers) {
        if (params.domain && layer.domain !== params.domain) continue;
        const option = el(
          "option",
          layer.label +
            ` (+${layer.new} / ~${layer.updated} / −${layer.removed})`,
        );
        option.value = layer.table_name;
        $("detail-table").append(option);
      }
    }
    $("changes").replaceChildren();
    for (const change of data.changes) {
      const item = el("article", undefined, "change"),
        title = el("div", undefined, "change-title");
      title.append(
        el("span", kinds[change.change_type], "status"),
        el("strong", change.label),
      );
      item.append(
        title,
        el(
          "div",
          Object.entries(change.record_key)
            .map(([k, v]) => `${k}: ${v ?? "∅"}`)
            .join(" · "),
          "change-key",
        ),
      );
      if (change.geometry_changed)
        item.append(el("p", "Άλλαξε και η γεωμετρία.", "updated"));
      if (change.old_source_id !== change.new_source_id)
        item.append(
          el(
            "p",
            `ID πηγής: ${change.old_source_id ?? "—"} → ${change.new_source_id ?? "—"}`,
            "technical",
          ),
        );
      const table = el("table"),
        head = el("tr");
      for (const value of ["Πεδίο", "Πριν", "Μετά"])
        head.append(el("th", value));
      const thead = el("thead");
      thead.append(head);
      table.append(thead);
      const body = el("tbody");
      for (const field of change.changed_fields) {
        const row = el("tr");
        row.append(el("td", field));
        for (const values of [change.old_values, change.new_values]) {
          const value = values?.[field];
          row.append(
            el(
              "td",
              value === null || value === undefined
                ? "—"
                : typeof value === "object"
                  ? JSON.stringify(value)
                  : String(value),
            ),
          );
        }
        body.append(row);
      }
      table.append(body);
      if (change.changed_fields.length) item.append(table);
      else
        item.append(
          el(
            "p",
            change.change_type === "source_id"
              ? "Τα δεδομένα και η γεωμετρία παρέμειναν ίδια."
              : "Δεν άλλαξαν περιγραφικά πεδία.",
            "technical",
          ),
        );
      $("changes").append(item);
    }
    if (!data.changes.length)
      $("changes").append(
        el(
          "div",
          data.run.status === "committed"
            ? "Δεν υπάρχουν αλλαγές με αυτά τα φίλτρα."
            : "Δεν υπάρχει επιβεβαιωμένη δημοσίευση για αυτή την εκτέλεση.",
          "empty",
        ),
      );
    pageButtons("changes", changeOffset, data.total_changes);
  } catch (error) {
    if (serial !== detailSerial) return;
    $("changes").replaceChildren(el("div", error.message, "notice error"));
    pageButtons("changes", 0, 0);
  }
}
$("period").onchange = () => {
  const custom = $("period").value === "custom";
  $("start-wrap").hidden = !custom;
  $("end-wrap").hidden = !custom;
};
$("filters").onsubmit = (event) => {
  event.preventDefault();
  runOffset = 0;
  $("detail").hidden = true;
  runId = null;
  ++detailSerial;
  loadOverview();
};
$("runs-prev").onclick = () => {
  runOffset = Math.max(0, runOffset - 25);
  loadOverview();
};
$("runs-next").onclick = () => {
  runOffset += 25;
  loadOverview();
};
$("detail-filters").onsubmit = (event) => {
  event.preventDefault();
  changeOffset = 0;
  loadDetails();
};
$("changes-prev").onclick = () => {
  changeOffset = Math.max(0, changeOffset - 25);
  loadDetails();
};
$("changes-next").onclick = () => {
  changeOffset += 25;
  loadDetails();
};
$("close-detail").onclick = () => {
  $("detail").hidden = true;
  runId = null;
  ++detailSerial;
};
pageButtons("runs", 0, 0);
pageButtons("changes", 0, 0);
loadOverview();
