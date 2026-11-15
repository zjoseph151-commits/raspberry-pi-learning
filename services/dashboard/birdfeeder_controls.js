(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var controls = document.querySelector("[data-birdfeeder-controls]");
    if (!controls) return;

    var buttons = Array.from(controls.querySelectorAll("[data-birdfeeder-command]"));
    var duration = controls.querySelector("[data-stream-duration]");
    var result = controls.querySelector("[data-command-result]");
    var streamAddress = controls.querySelector("[data-stream-address]");
    var streamLink = controls.querySelector("[data-stream-link]");
    var streamState = controls.querySelector("[data-stream-state]");
    var lastAddress = controls.dataset.streamUrl || "";
    var streamKey = "pi-iot-birdfeeder-stream";
    var resultKey = "pi-iot-birdfeeder-command-result";

    function readStored(key) {
      try {
        return JSON.parse(sessionStorage.getItem(key) || "null");
      } catch (error) {
        return null;
      }
    }

    function writeStored(key, value) {
      try {
        sessionStorage.setItem(key, JSON.stringify(value));
      } catch (error) {
      }
    }

    function removeStored(key) {
      try {
        sessionStorage.removeItem(key);
      } catch (error) {
      }
    }

    function showResult(message, failed) {
      result.textContent = message;
      result.classList.toggle("error", failed);
      writeStored(resultKey, {
        message: message,
        failed: failed,
        expiresAt: Date.now() + 60000
      });
    }

    function refreshStream() {
      var active = readStored(streamKey);
      if (!active || !active.url || active.expiresAt <= Date.now()) {
        if (active) removeStored(streamKey);
        streamAddress.textContent = lastAddress || "Unavailable";
        streamLink.hidden = true;
        streamLink.removeAttribute("href");
        streamState.textContent = "Inactive";
        return;
      }
      streamAddress.textContent = active.url;
      streamLink.href = active.url;
      streamLink.hidden = false;
      streamState.textContent = "Active";
    }

    var previousResult = readStored(resultKey);
    if (previousResult && previousResult.expiresAt > Date.now()) {
      result.textContent = previousResult.message;
      result.classList.toggle("error", previousResult.failed === true);
    } else {
      removeStored(resultKey);
    }
    refreshStream();
    setInterval(refreshStream, 1000);

    buttons.forEach(function (button) {
      button.addEventListener("click", async function () {
        var command = button.dataset.birdfeederCommand;
        var body = { command: command };
        if (command === "stream_on") {
          body.duration_seconds = Number(duration.value);
        }
        buttons.forEach(function (item) { item.disabled = true; });
        duration.disabled = true;
        result.textContent = "Sending...";
        result.classList.remove("error");
        window.dashboardDeferRefresh(20000);

        try {
          var response = await fetch("/api/devices/birdfeeder-01/commands", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Dashboard-Action": "1" },
            body: JSON.stringify(body),
            cache: "no-store",
            credentials: "same-origin"
          });
          var data = await response.json();
          var message = String(data.message || (data.ok ? "Command acknowledged" : "Command failed"));
          message = message.replace(/_/g, " ");
          message = message.charAt(0).toUpperCase() + message.slice(1);
          showResult(message, !response.ok || !data.ok);

          if (response.ok && data.ok && command === "stream_on" && data.stream_url) {
            writeStored(streamKey, {
              url: data.stream_url,
              expiresAt: Date.now() + Number(data.duration_seconds || 60) * 1000
            });
            refreshStream();
          } else if (response.ok && data.ok && command === "sleep_now") {
            removeStored(streamKey);
            refreshStream();
          }
        } catch (error) {
          showResult("Could not reach dashboard", true);
        } finally {
          buttons.forEach(function (item) { item.disabled = false; });
          duration.disabled = false;
          window.dashboardDeferRefresh(10000);
        }
      });
    });
  });
})();
