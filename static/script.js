(function () {
  const form = document.getElementById("download-form");
  const input = document.getElementById("url-input");
  const btn = document.getElementById("action-btn");
  const btnLabel = btn.querySelector(".btn-label");
  const message = document.getElementById("message");
  const videoTitle = document.getElementById("video-title");

  let currentJobId = null;
  let pollTimer = null;

  function setState(state, label) {
    btn.dataset.state = state;
    btnLabel.textContent = label;
    btn.disabled = state === "loading";
  }

  function setMessage(text, tone) {
    message.textContent = text || "";
    if (tone) {
      message.dataset.tone = tone;
    } else {
      delete message.dataset.tone;
    }
  }

  function resetToIdle() {
    currentJobId = null;
    clearInterval(pollTimer);
    setState("idle", "Submit");
  }

  async function startJob(url) {
    setState("loading", "Loading...");
    setMessage("Fetching video info from YouTube...");
    videoTitle.textContent = "";

    let res, data;
    try {
      res = await fetch("/api/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      data = await res.json();
    } catch (err) {
      setMessage("Couldn't reach the server. Try again.", "error");
      resetToIdle();
      return;
    }

    if (!res.ok) {
      setMessage(data.error || "Something went wrong.", "error");
      resetToIdle();
      return;
    }

    currentJobId = data.job_id;
    pollTimer = setInterval(() => pollStatus(currentJobId), 2000);
  }

  async function pollStatus(jobId) {
    if (jobId !== currentJobId) return;

    let res, data;
    try {
      res = await fetch(`/api/status/${jobId}`);
      data = await res.json();
    } catch (err) {
      return; // transient network hiccup, keep polling
    }

    if (data.status === "done") {
      clearInterval(pollTimer);
      setState("done", "Download");
      setMessage("Ready.", "success");
      videoTitle.textContent = data.title || "";
    } else if (data.status === "error") {
      clearInterval(pollTimer);
      setMessage(data.error || "Couldn't process that link.", "error");
      resetToIdle();
    }
    // status === "processing" -> keep polling silently
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();

    const state = btn.dataset.state;

    if (state === "done" && currentJobId) {
      // Trigger the actual file download
      window.location.href = `/api/download/${currentJobId}`;
      setMessage("Download started.", "success");
      resetToIdle();
      input.value = "";
      videoTitle.textContent = "";
      return;
    }

    if (state === "loading") return; // already working

    const url = input.value.trim();
    if (!url) {
      setMessage("Paste a YouTube link first.", "error");
      return;
    }
    startJob(url);
  });
})();
