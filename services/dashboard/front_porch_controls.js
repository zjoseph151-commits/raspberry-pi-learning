(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var controls = document.querySelector("[data-porch-controls]");
    if (!controls) return;

    var buttons = Array.from(controls.querySelectorAll("[data-porch-command]"));
    var duration = controls.querySelector("[data-stream-duration]");
    var result = controls.querySelector("[data-command-result]");
    var streamAddress = controls.querySelector("[data-stream-address]");
    var streamLink = controls.querySelector("[data-stream-link]");
    var streamState = controls.querySelector("[data-stream-state]");
    var snapshotUrl = controls.dataset.streamUrl || "";
    var snapshotAt = Date.parse(controls.dataset.statusAt || "") || 0;
    var snapshotRemaining = Number(controls.dataset.streamRemaining) || 0;
    var stateKey = "pi-iot-front-porch-stream";
    var resultKey = "pi-iot-front-porch-command-result";

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
      var now = Date.now();
      var current = readStored(stateKey);
      if (current && (current.expiresAt <= now || snapshotAt > current.observedAt)) {
        removeStored(stateKey);
        current = null;
      }
      var active = current
        ? current.active && current.expiresAt > now
        : controls.dataset.streamActive === "true" && snapshotRemaining > 0 &&
          (snapshotAt === 0 || snapshotAt + snapshotRemaining * 1000 > now);
      var url = (current && current.url) || snapshotUrl;
      streamAddress.textContent = url || "Unavailable";
      streamLink.hidden = !active || !url;
      if (active && url) {
        streamLink.href = url;
      } else {
        streamLink.removeAttribute("href");
      }
      streamState.textContent = active ? "Active" : "Inactive";
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
        var command = button.dataset.porchCommand;
        var body = { command: command };
        if (command === "start_stream") {
          body.duration_seconds = Number(duration.value);
        }
        buttons.forEach(function (item) { item.disabled = true; });
        duration.disabled = true;
        result.textContent = "Sending...";
        result.classList.remove("error");
        window.dashboardDeferRefresh(20000);

        try {
          var response = await fetch("/api/devices/front-porch-camera-01/commands", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            cache: "no-store",
            credentials: "same-origin"
          });
          var data = await response.json();
          var message = String(data.message || (data.ok ? "Command acknowledged" : "Command failed"));
          message = message.replace(/_/g, " ");
          message = message.charAt(0).toUpperCase() + message.slice(1);
          showResult(message, !response.ok || !data.ok);

          if (response.ok && data.ok) {
            var remaining = Number(data.stream_remaining_seconds) || 0;
            var active = data.stream_active === true && remaining > 0;
            writeStored(stateKey, {
              active: active,
              url: data.stream_url || snapshotUrl,
              observedAt: Date.now(),
              expiresAt: Date.now() + (active ? remaining : 70) * 1000
            });
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
