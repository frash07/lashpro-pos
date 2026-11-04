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
