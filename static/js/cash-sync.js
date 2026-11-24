/* Store each walk-in cash sale independently so another tab cannot overwrite it. */
function setupCashSync({cashierId, cashSessionId, offlineShell, syncUrl, checkoutUrl, workerUrl}) {
  const prefix = `lashpro.cash.v1.${cashierId}.`;
  const panel = document.getElementById("cash-sync-panel");
  const status = document.getElementById("cash-sync-status");
  const orders = document.getElementById("cash-sync-orders");
  const feedback = document.getElementById("cash-save-feedback");
  const retry = document.getElementById("cash-sync-retry");
  const recentlySynced = [];
  let syncing = false;
  let preparing = false;

  function savedSales() {
    return Object.keys(localStorage)
      .filter(key => key.startsWith(prefix))
      .map(key => JSON.parse(localStorage.getItem(key)))
      .filter(Boolean)
      .sort((a, b) => a.savedAt - b.savedAt);
  }

  function render(message = "") {
    let saved;
    try {
      saved = savedSales();
    } catch {
      panel.hidden = false;
      status.textContent = "Saved cash sales are unavailable. Check this device’s browser storage.";
      return;
    }
    panel.hidden = !offlineShell && navigator.onLine && !message && !saved.length && !recentlySynced.length;
    status.textContent = message || (offlineShell || !navigator.onLine
      ? "Offline checkout uses the last saved catalogue. Walk-in cash sales sync when a connection is available."
      : "Saved cash sales");
    orders.replaceChildren();
    for (const sale of [...saved, ...recentlySynced]) {
      const row = document.createElement("li");
      row.textContent = `${sale.id.slice(0, 8)} · ${new Date(sale.savedAt).toLocaleString()} · KES ${sale.amount} · ${sale.items.join(", ")} · `;
      if (sale.receipt) {
        const link = document.createElement("a");
        link.href = sale.receipt;
        link.textContent = "Synced · View receipt";
        row.append(link);
      } else {
        row.append(sale.error ? `Needs review · ${sale.error}` : "Saved on this device · Awaiting sync");
      }
      orders.append(row);
    }
    retry.disabled = syncing || !saved.length || !navigator.onLine;
  }

  async function sync(retryConflicts = false) {
    if (syncing || !navigator.onLine || document.hidden) return;
    let sales;
    try {
      sales = savedSales().filter(sale => retryConflicts || !sale.error);
    } catch {
      render();
      return;
    }
    if (!sales.length) return;
    syncing = true;
    render("Syncing saved cash sales…");
    let message = "";
    try {
      const session = await fetch(syncUrl, {cache: "no-store", signal: AbortSignal.timeout(8000)});
      if (session.status === 401 || session.status === 403) {
        message = "Sign in as the original cashier to sync saved cash sales.";
        return;
      }
      if (!session.ok) throw new Error("Checkout unavailable");
      const {cashier_id, csrf} = await session.json();
      if (cashier_id !== cashierId) {
        message = "Sign in as the original cashier to sync saved cash sales.";
        return;
      }
      for (const sale of sales) {
        const response = await fetch(syncUrl, {
          method: "POST",
          headers: {"X-CSRFToken": csrf},
          body: new URLSearchParams(sale.fields),
          signal: AbortSignal.timeout(12000),
        });
        if (response.status === 401 || response.status === 403) {
          message = "Your session changed. Sign in as the original cashier to sync.";
          return;
        }
        const result = await response.json();
        const key = prefix + sale.id;
        if (response.status === 409) {
          // Another tab may already have resolved this record. Never restore a removed entry.
          if (localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify({...sale, error: result.error}));
          continue;
        }
        if (!response.ok || !result.receipt) throw new Error("Checkout unavailable");
        localStorage.removeItem(key);
        recentlySynced.unshift({...sale, receipt: result.receipt});
        recentlySynced.splice(5);
      }
    } catch {
      message = "Connection interrupted. Saved cash sales will retry automatically.";
    } finally {
      syncing = false;
      render(message);
    }
  }

  function save(form, amount, items) {
    feedback.textContent = "";
    if (!cashSessionId) {
      feedback.textContent = "Open a cash session while connected, then reload checkout.";
      return false;
    }
    if (items.length > 20 || Number(amount) <= 0) {
      feedback.textContent = "Cash checkout requires 1–20 lines and a positive amount.";
      return false;
    }
    try {
      const id = crypto.randomUUID();
      const fields = [...new FormData(form)].filter(([name]) => name.startsWith("items-"));
      fields.push(["idempotency_key", id], ["cashier_id", cashierId], ["cash_session_id", cashSessionId], ["amount", amount]);
      const sale = {id, amount, fields, savedAt: Date.now(), items: items.map(item => `${item.qty} × ${item.name}`)};
      localStorage.setItem(prefix + id, JSON.stringify(sale));
    } catch {
      feedback.textContent = "This device could not save the sale. Keep the order open and check browser storage.";
      return false;
    }
    feedback.textContent = "Cash sale saved on this device. See Saved cash sales for sync status.";
    render();
    void sync();
    return true;
  }

  async function prepareOfflineCheckout() {
    if (offlineShell || !navigator.onLine || preparing || !("serviceWorker" in navigator)) return;
    preparing = true;
    try {
      await navigator.serviceWorker.register(workerUrl, {scope: "/"});
      await navigator.serviceWorker.ready;
      if (!navigator.serviceWorker.controller) return;
      await fetch(`${checkoutUrl}?offline-shell=1`, {cache: "no-store", signal: AbortSignal.timeout(10000)});
    } catch {
      // A later online event refreshes the offline shell.
    } finally {
      preparing = false;
    }
  }

  navigator.serviceWorker?.addEventListener("controllerchange", prepareOfflineCheckout);
  retry.addEventListener("click", () => void sync(true));
  window.addEventListener("online", () => { render(); void sync(); void prepareOfflineCheckout(); });
  window.addEventListener("offline", () => render());
  window.addEventListener("storage", event => { if (!event.key || event.key.startsWith(prefix)) render(); });
  document.addEventListener("visibilitychange", () => void sync());
  window.setInterval(() => void sync(), 15000);
  window.setInterval(() => void prepareOfflineCheckout(), 300000);
  render();
  void sync();
  void prepareOfflineCheckout();
  return {save};
}
