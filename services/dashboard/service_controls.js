(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var services = document.querySelector(".services");
    if (!services) return;

    var buttons = Array.from(services.querySelectorAll("[data-service-action]"));
    var result = services.querySelector("[data-service-result]");
    var resultKey = "pi-iot-service-action-result";

    function showResult(message, failed) {
      result.textContent = message;
      result.classList.toggle("error", failed);
      try {
        sessionStorage.setItem(resultKey, JSON.stringify({
          message: message,
          failed: failed,
          expiresAt: Date.now() + 30000
        }));
      } catch (error) {
      }
    }

    try {
      var previous = JSON.parse(sessionStorage.getItem(resultKey) || "null");
      if (previous && previous.expiresAt > Date.now()) {
        result.textContent = previous.message;
        result.classList.toggle("error", previous.failed === true);
      } else {
        sessionStorage.removeItem(resultKey);
      }
    } catch (error) {
    }

    async function reconnect() {
      window.dashboardDeferRefresh(40000);
      for (var attempt = 0; attempt < 30; attempt += 1) {
        await new Promise(function (resolve) { setTimeout(resolve, 1000); });
        try {
          var response = await fetch("/", { cache: "no-store" });
          if (response.ok) {
            window.location.reload();
            return;
          }
        } catch (error) {
        }
      }
      showResult("Dashboard has not returned yet. Refresh to check its status.", true);
    }

    buttons.forEach(function (button) {
      button.addEventListener("click", async function () {
        var unit = button.dataset.serviceUnit;
        var action = button.dataset.serviceAction;
        var label = button.closest("tr").querySelector("strong").textContent;
        var verb = action === "start" ? "Run" : "Restart";
        if (!window.confirm(verb + " " + label + "?")) return;

        buttons.forEach(function (item) { item.disabled = true; });
        result.textContent = verb + " requested...";
        result.classList.remove("error");
        window.dashboardDeferRefresh(15000);

        var reconnecting = false;
        try {
          var response = await fetch("/api/services/actions", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Dashboard-Action": "1" },
            body: JSON.stringify({ unit: unit, action: action }),
            cache: "no-store",
            credentials: "same-origin"
          });
          var data = await response.json();
          showResult(String(data.message || "Service action failed"), !response.ok || !data.ok);
          if (response.ok && data.ok && unit === "iot-dashboard.service") {
            reconnecting = true;
            showResult("Dashboard restart requested. Reconnecting...", false);
            await reconnect();
          }
        } catch (error) {
          if (unit === "iot-dashboard.service") {
            reconnecting = true;
            showResult("Dashboard connection closed. Reconnecting...", false);
            await reconnect();
          } else {
            showResult("Could not reach dashboard", true);
          }
        } finally {
          if (!reconnecting) {
            buttons.forEach(function (item) { item.disabled = false; });
            window.dashboardDeferRefresh(10000);
          }
        }
      });
    });
  });
})();
