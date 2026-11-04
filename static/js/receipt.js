// A rendered receipt confirms the checkout completed; only now discard the retry payload.
try {
  window.sessionStorage.removeItem("lashpro.pos.pendingCheckout.v1");
} catch (error) {
  // Storage may be disabled; the receipt remains authoritative.
}

document.getElementById("share-receipt")?.addEventListener("click", async () => {
  const url = window.location.href;
  try {
    if (navigator.share) {
      await navigator.share({ title: document.title, url });
    } else if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
      window.alert("Receipt link copied.");
    } else {
      window.prompt("Copy this receipt link:", url);
    }
  } catch (error) {
    if (error.name !== "AbortError") window.prompt("Copy this receipt link:", url);
  }
});
