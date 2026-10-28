(function () {
  const checkoutForm = document.getElementById("checkout");
  const register = document.getElementById("register-panel");
  const backdrop = document.getElementById("register-backdrop");
  const registerToggle = document.getElementById("register-toggle");
  const registerClose = document.getElementById("register-close");

  if (!checkoutForm || !register || !backdrop || !registerToggle) {
    return;
  }

  const pricesElement = document.getElementById("prices");
  const prices = pricesElement ? JSON.parse(pricesElement.textContent) : { products: {}, services: {} };
  const format = (n) => new Intl.NumberFormat("en-KE", { style: "currency", currency: "KES" }).format(Number(n) || 0);
  const field = (row, name) => row.querySelector('[name$="-' + name + '"]');
  const activeRows = (selector) => [...document.querySelectorAll(selector)].filter((row) => {
    const deleted = row.querySelector('input[name$="-DELETE"]');
    return !deleted || !deleted.checked;
  });
  const rows = () => activeRows("#items [data-item-row]");
  const payments = () => activeRows("#payments [data-payment-row]");
  const productPrices = prices?.products ?? {};
  const servicePrices = prices?.services ?? {};

  let orderTotal = 0;
  let noticeTimer = null;

  function showNotice(message) {
    const notice = document.getElementById("pos-notice");
    if (!notice) return;
    notice.textContent = message;
    notice.hidden = false;
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => {
      notice.hidden = true;
    }, 2800);
  }

  function setRegisterOpen(open) {
    register.classList.toggle("is-open", open);
    backdrop.hidden = !open;
    registerToggle.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("register-open", open);
  }

  if (registerClose) {
    registerClose.addEventListener("click", () => setRegisterOpen(false));
  }
  registerToggle.addEventListener("click", () => setRegisterOpen(!register.classList.contains("is-open")));
  backdrop.addEventListener("click", () => setRegisterOpen(false));

  const applyPromo = document.getElementById("apply-promo");
  const stkPayment = document.getElementById("stk-payment");
  const cardPayment = document.getElementById("card-payment");

  if (applyPromo) {
    applyPromo.addEventListener("click", () => showNotice("Promo and student codes are not connected yet. No discount was applied."));
  }
  if (stkPayment) {
    stkPayment.addEventListener("click", () => showNotice("M-PESA Express is not connected yet. Use the manual M-Pesa reference option to record a payment."));
  }
  if (cardPayment) {
    cardPayment.addEventListener("click", () => showNotice("Card / PDQ processing is not connected yet. You can record cash or a manual M-Pesa reference."));
  }

  function cardFor(kind, id) {
    return [...document.querySelectorAll("[data-catalog-card]")].find((card) => card.dataset.itemKind === kind && card.dataset.itemId === String(id));
  }

  function remainingBalance(exceptRow = null) {
    let cash = 0;
    let mpesa = 0;

    payments().filter((row) => row !== exceptRow).forEach((row) => {
      const amount = Number(field(row, "amount").value) || 0;
      const method = field(row, "method").value;
      if (method === "CASH") cash += amount;
      else if (method === "MPESA") mpesa += amount;
    });

    const afterMpesa = Math.max(0, orderTotal - Math.min(mpesa, orderTotal));
    return Math.max(0, afterMpesa - Math.min(cash, afterMpesa));
  }

  function update() {
    let total = 0;
    let count = 0;
    let cash = 0;
    let mpesa = 0;

    rows().forEach((row) => {
      const product = field(row, "product");
      const service = field(row, "service");
      const productId = product.value;
      const serviceId = service.value;
      const kind = productId ? "product" : serviceId ? "service" : "";
      const id = productId || serviceId;
      const selected = !!id;
      const tech = field(row, "technician");
      const techField = row.querySelector("[data-technician-field]");

      if (techField) {
        techField.hidden = !serviceId;
        if (tech) {
          tech.required = !!serviceId;
          if (!serviceId) tech.value = "";
        }
      }

      const hasErrors = row.dataset.hasErrors === "true";
      row.classList.toggle("is-empty", !selected && !hasErrors);
      if (!selected) return;

      const card = cardFor(kind, id);
      const select = productId ? product : service;
      const name = card?.dataset.itemName || select.options[select.selectedIndex]?.text.split(" — KSh ")[0] || "Catalog item";
      const meta = card?.dataset.itemMeta || (kind === "service" ? "Lash service" : "Retail product");
      const itemPrice = kind === "product"
        ? Number(productPrices[id] ?? 0)
        : Number(servicePrices[id] ?? 0);
      const qtyField = field(row, "quantity");
      const quantity = Math.max(1, Number(qtyField.value) || 1);
      const discountField = field(row, "discount");
      const discount = discountField ? Number(discountField.value) || 0 : 0;
      const lineTotal = Math.max(0, itemPrice * quantity - discount);

      const lineName = row.querySelector("[data-line-name]");
      const lineMeta = row.querySelector("[data-line-meta]");
      const lineQuantity = row.querySelector("[data-line-quantity]");
      const lineTotalEl = row.querySelector("[data-line-total]");

      if (lineName) lineName.textContent = name;
      if (lineMeta) lineMeta.textContent = meta;
      if (lineQuantity) lineQuantity.textContent = "× " + quantity;
      if (lineTotalEl) lineTotalEl.textContent = format(lineTotal);
      const thumb = row.querySelector("[data-line-thumb]");
      const cardImage = card?.querySelector("img");
      if (thumb && cardImage) {
        thumb.src = cardImage.getAttribute("src") || "";
        thumb.hidden = !thumb.src;
      }

      total += lineTotal;
      count += quantity;
    });

    payments().forEach((row) => {
      const method = field(row, "method");
      const amount = Number(field(row, "amount").value) || 0;
      const reference = row.querySelector("[data-reference-field]");
      const value = method.value;
      const referenceField = field(row, "reference");

      row.classList.toggle("is-empty", !value && amount === 0 && !(referenceField ? referenceField.value : ""));
      if (reference) reference.hidden = value !== "MPESA";
      if (value === "CASH") cash += amount;
      else if (value === "MPESA") mpesa += amount;
    });

    orderTotal = total;
    const mpesaApplied = Math.min(mpesa, total);
    const afterMpesa = Math.max(0, total - mpesaApplied);
    const cashApplied = Math.min(cash, afterMpesa);
    const change = Math.max(0, cash - cashApplied);
    const balance = Math.max(0, afterMpesa - cashApplied);
    const vat = total * 16 / 116;

    const subtotalEl = document.getElementById("subtotal");
    const vatEl = document.getElementById("vat");
    const totalEl = document.getElementById("total");
    const cashReceivedEl = document.getElementById("cash-received");
    const cashChangeEl = document.getElementById("cash-change");
    const mpesaPendingEl = document.getElementById("mpesa-pending");
    const balanceDueEl = document.getElementById("balance-due");
    const cartEmpty = document.getElementById("cart-empty");
    const registerCount = document.getElementById("register-count");
    const registerMobileTotal = document.getElementById("register-mobile-total");

    if (subtotalEl) subtotalEl.textContent = format(total - vat);
    if (vatEl) vatEl.textContent = format(vat);
    if (totalEl) totalEl.textContent = format(total);
    if (cashReceivedEl) cashReceivedEl.textContent = format(cash);
    if (cashChangeEl) cashChangeEl.textContent = format(change);
    if (mpesaPendingEl) mpesaPendingEl.textContent = format(mpesa);
    if (balanceDueEl) balanceDueEl.textContent = format(balance);
    if (cartEmpty) cartEmpty.hidden = count > 0;
    register.classList.toggle("has-items", count > 0);
    if (registerCount) registerCount.textContent = String(count);
    if (registerMobileTotal) registerMobileTotal.textContent = format(total);
    const submitTotal = document.getElementById("submit-total");
    if (submitTotal) submitTotal.textContent = format(total);
    const paymentRows = document.getElementById("payments");
    if (paymentRows && payments().length) paymentRows.hidden = false;
    const phoneField = document.getElementById("mpesa-phone-field");
    if (phoneField) phoneField.hidden = mpesa <= 0;
  }

  function addRow(containerId, templateId, prefix) {
    const totalForms = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
    const host = document.getElementById(containerId);
    const template = document.getElementById(templateId);

    if (!totalForms || !host || !template) return null;

    const index = Number(totalForms.value);
    host.insertAdjacentHTML("beforeend", template.innerHTML.replaceAll("__prefix__", index));
    totalForms.value = index + 1;
    return host.lastElementChild;
  }

  function addPayment(method) {
    const row = addRow("payments", "payment-template", "payments");
    if (!row) return;

    field(row, "method").value = method;
    field(row, "method").dispatchEvent(new Event("change", { bubbles: true }));
    const due = remainingBalance(row);
    field(row, "amount").value = due > 0 ? due.toFixed(2) : "";
    update();
    if (method === "MPESA") {
      const refField = field(row, "reference");
      if (refField) refField.focus();
    }
  }

  document.querySelectorAll("[data-catalog-card]").forEach((card) => {
    card.addEventListener("click", () => {
      const kind = card.dataset.itemKind;
      const id = card.dataset.itemId;
      const existing = rows().find((row) => field(row, kind).value === id);

      if (existing) {
        const qty = field(existing, "quantity");
        if (qty) {
          qty.value = (Number(qty.value) || 1) + 1;
          qty.dispatchEvent(new Event("input", { bubbles: true }));
        }
        return;
      }

      let row = rows().find((item) => !field(item, "product").value && !field(item, "service").value);
      if (!row) row = addRow("items", "item-template", "items");
      if (!row) return;

      field(row, kind).value = id;
      const other = field(row, kind === "product" ? "service" : "product");
      if (other) other.value = "";

      const defaultTechnician = document.getElementById("default-technician");
      if (kind === "service" && defaultTechnician && defaultTechnician.value) {
        const technicianField = field(row, "technician");
        if (technicianField) technicianField.value = defaultTechnician.value;
      }

      field(row, kind).dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  const defaultTechnician = document.getElementById("default-technician");
  if (defaultTechnician) {
    defaultTechnician.addEventListener("change", (event) => {
      rows().forEach((row) => {
        const serviceField = field(row, "service");
        const technicianField = field(row, "technician");
        if (serviceField && serviceField.value && technicianField) {
          technicianField.value = event.target.value;
        }
      });
    });
  }

  checkoutForm.addEventListener("input", update);
  checkoutForm.addEventListener("change", (event) => {
    const row = event.target.closest("[data-item-row]");
    if (row && event.target.name.endsWith("-product") && event.target.value) {
      const service = field(row, "service");
      const tech = field(row, "technician");
      if (service) service.value = "";
      if (tech) tech.value = "";
    }
    if (row && event.target.name.endsWith("-service") && event.target.value) {
      const product = field(row, "product");
      const tech = field(row, "technician");
      if (product) product.value = "";
      if (tech && !tech.value && defaultTechnician) {
        tech.value = defaultTechnician.value;
      }
    }
    update();
  });

  document.querySelectorAll("[data-add-payment]").forEach((button) => {
    button.addEventListener("click", () => addPayment(button.dataset.addPayment));
  });

  const fillBalanceButton = document.getElementById("fill-balance");
  const cashOption = document.querySelector(".cash-option");

  if (fillBalanceButton) {
    fillBalanceButton.addEventListener("click", () => {
      let target = payments().slice().reverse().find((row) => field(row, "method").value === "CASH") || payments().slice().reverse().find((row) => field(row, "method").value === "MPESA");
      if (!target) target = payments().find((row) => !field(row, "method").value);
      if (!target) {
        if (cashOption && !cashOption.disabled) {
          target = addRow("payments", "payment-template", "payments");
          if (target) field(target, "method").value = "CASH";
        } else {
          showNotice("Open a cash session before accepting cash payments.");
          return;
        }
      }
      if (target && !field(target, "method").value) {
        field(target, "method").value = cashOption && cashOption.disabled ? "MPESA" : "CASH";
      }
      if (!target) return;

      const due = remainingBalance(target);
      field(target, "amount").value = due.toFixed(2);
      update();
      if (field(target, "method").value === "MPESA") {
        const refField = field(target, "reference");
        if (refField && !refField.value) refField.focus();
      }
    });
  }

  checkoutForm.addEventListener("click", (event) => {
    const step = event.target.closest("[data-qty-step]");
    if (step) {
      const row = step.closest("[data-item-row]");
      const qty = field(row, "quantity");
      if (qty) {
        qty.value = Math.max(1, (Number(qty.value) || 1) + Number(step.dataset.qtyStep));
        qty.dispatchEvent(new Event("input", { bubbles: true }));
      }
      return;
    }

    const remove = event.target.closest("[data-remove]");
    if (remove) {
      const row = remove.closest("[data-item-row],[data-payment-row]");
      if (!row) return;
      const deleted = row.querySelector('input[name$="-DELETE"]');
      if (deleted) {
        deleted.checked = true;
        row.hidden = true;
      }
      update();
    }
  });

  const clearItemsButton = document.getElementById("clear-items");
  if (clearItemsButton) {
    clearItemsButton.addEventListener("click", () => {
      const hasItems = rows().some((row) => field(row, "product").value || field(row, "service").value);
      const hasPayments = payments().some((row) => field(row, "method").value || field(row, "amount").value || field(row, "reference").value);

      if (!hasItems && !hasPayments) return;
      if (!window.confirm("Clear this order and its payment entries?")) return;

      document.querySelectorAll("#items [data-item-row]").forEach((row) => {
        const product = field(row, "product");
        const service = field(row, "service");
        const technician = field(row, "technician");
        const quantity = field(row, "quantity");
        if (product) product.value = "";
        if (service) service.value = "";
        if (technician) technician.value = "";
        if (quantity) quantity.value = "1";
        row.hidden = false;
        row.classList.remove("is-empty");
        const deleted = row.querySelector('input[name$="-DELETE"]');
        if (deleted) deleted.checked = false;
      });

      document.querySelectorAll("#payments [data-payment-row]").forEach((row) => {
        const method = field(row, "method");
        const amount = field(row, "amount");
        const reference = field(row, "reference");
        if (method) method.value = "";
        if (amount) amount.value = "";
        if (reference) reference.value = "";
        row.hidden = false;
        const deleted = row.querySelector('input[name$="-DELETE"]');
        if (deleted) deleted.checked = false;
      });

      const promoCode = document.getElementById("promo-code");
      if (promoCode) promoCode.value = "";
      update();
    });
  }

  const search = document.getElementById("catalog-search");
  let activeCategory = "all";

  function filterCatalog() {
    if (!search) return;
    const query = search.value.trim().toLocaleLowerCase();
    document.querySelectorAll("[data-catalog-card]").forEach((card) => {
      card.hidden = (activeCategory !== "all" && card.dataset.category !== activeCategory) || !card.textContent.toLocaleLowerCase().includes(query);
    });

    const trainingEmpty = document.getElementById("training-empty");
    if (trainingEmpty) {
      const anyTraining = document.querySelector("[data-catalog-card][data-category='training']");
      trainingEmpty.hidden = activeCategory !== "training" || !!anyTraining || !!query;
    }
  }

  if (search) {
    search.addEventListener("input", filterCatalog);
  }

  document.querySelectorAll(".catalog-filter").forEach((button) => {
    button.addEventListener("click", () => {
      activeCategory = button.dataset.category;
      document.querySelectorAll(".catalog-filter").forEach((tab) => {
        const selected = tab === button;
        tab.classList.toggle("is-active", selected);
        tab.setAttribute("aria-pressed", String(selected));
      });
      filterCatalog();
    });
  });

  document.querySelectorAll("[data-payment-row]").forEach((row) => {
    const method = field(row, "method");
    if (method) method.addEventListener("change", update);
  });

  const submitButton = checkoutForm.querySelector(".checkout-submit");
  if (submitButton) {
    checkoutForm.addEventListener("submit", () => {
      submitButton.disabled = true;
      submitButton.textContent = "Completing sale…";
    });
  }

  const online = document.getElementById("network-status");
  function networkState() {
    if (!online) return;
    online.textContent = navigator.onLine ? "Online" : "Offline";
    online.parentElement.classList.toggle("is-offline", !navigator.onLine);
  }

  window.addEventListener("online", networkState);
  window.addEventListener("offline", networkState);
  networkState();

  let installPrompt = null;
  const installButton = document.getElementById("install-app");
  if (installButton) {
    window.addEventListener("beforeinstallprompt", (event) => {
      event.preventDefault();
      installPrompt = event;
      installButton.hidden = false;
    });

    installButton.addEventListener("click", async () => {
      if (!installPrompt) return;
      installPrompt.prompt();
      await installPrompt.userChoice;
      installPrompt = null;
      installButton.hidden = true;
    });
  }

  const splitPayments = document.getElementById("split-payments");
  if (splitPayments) {
    splitPayments.addEventListener("click", () => {
      const paymentRows = document.getElementById("payments");
      if (paymentRows) paymentRows.hidden = false;
      splitPayments.setAttribute("aria-pressed", "true");
    });
  }

  const clock = document.getElementById("pos-clock");
  if (clock) {
    const paintClock = () => {
      const now = new Date();
      clock.dateTime = now.toISOString();
      clock.textContent = now.toLocaleTimeString("en-KE", { hour: "2-digit", minute: "2-digit" });
    };
    paintClock();
    setInterval(paintClock, 30000);
  }

  filterCatalog();
  update();
})();
