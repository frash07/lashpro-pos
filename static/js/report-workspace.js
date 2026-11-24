/* Export the same executive metrics and masked audit fields shown in the report. */
(() => {
  const exportButton = document.getElementById("export-report");
  const quote = value => {
    const text = String(value ?? "");
    const safe = /^[\s]*[=+\-@]/.test(text) ? "'" + text : text;
    return '"' + safe.replace(/"/g, '""') + '"';
  };
  if (exportButton) {
    exportButton.hidden = false;
    exportButton.addEventListener("click", () => {
      const rows = [["LashPro KE Executive Report", document.getElementById("report-range").textContent.trim()], ["Metric", "Value"]];
      document.querySelectorAll("[data-export-label]").forEach(card => rows.push([card.dataset.exportLabel, card.dataset.exportValue]));
      rows.push([], ["M-PESA Reconciliation Audit Log"], ["Timestamp", "Receipt code", "Client phone", "Amount (KES)", "Status"]);
      document.querySelectorAll("[data-audit-row]").forEach(card => {
        const d = card.dataset;
        rows.push([d.timestamp, d.reference, d.phone, d.amount, d.status]);
      });
      const csv = "\uFEFF" + rows.map(row => row.map(quote).join(",")).join("\r\n");
      const url = URL.createObjectURL(new Blob([csv], {type: "text/csv;charset=utf-8"}));
      const download = document.createElement("a");
      download.href = url;
      download.download = "lashpro-executive-report.csv";
      document.body.appendChild(download);
      download.click();
      download.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }
  const button = document.getElementById("install-app");
  const feedback = document.getElementById("install-feedback");
  let prompt = null;
  if (button && feedback) {
    button.hidden = false;
    window.addEventListener("beforeinstallprompt", event => {
      event.preventDefault();
      prompt = event;
    });
    button.addEventListener("click", async () => {
      if (!prompt) {
        feedback.hidden = false;
        feedback.textContent = "To install LashPro, use your browser menu and choose Install App or Add to Home Screen.";
        return;
      }
      await prompt.prompt();
      await prompt.userChoice;
      prompt = null;
    });
    window.addEventListener("appinstalled", () => {
      feedback.hidden = false;
      feedback.textContent = "LashPro is installed on this device.";
    });
  }
  const worker = document.getElementById("report-pwa")?.dataset.workerUrl;
  if (worker && "serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register(worker, {scope: "/"}).catch(() => console.warn("LashPro offline support could not be enabled.")));
  }
})();
