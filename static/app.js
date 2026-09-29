// Loading feedback for slow, server-rendered requests (e.g. 알림 미리보기).
// A form or submit button marked with `data-loading` shows a spinner on the
// pressed button plus a full-page veil, and ignores repeat submits.
(() => {
  const veil = () => document.getElementById("loading-veil");
  let busy = false;

  function showLoading(button) {
    busy = true;
    if (button) {
      button.setAttribute("aria-busy", "true");
      const spinner = document.createElement("span");
      spinner.className = "spinner";
      spinner.setAttribute("aria-hidden", "true");
      button.prepend(spinner);
    }
    const element = veil();
    if (element) {
      element.hidden = false;
      requestAnimationFrame(() => element.classList.add("is-visible"));
    }
  }

  function reset() {
    busy = false;
    document.querySelectorAll('[aria-busy="true"]').forEach((button) => {
      button.removeAttribute("aria-busy");
      button.querySelectorAll(".spinner").forEach((spinner) => spinner.remove());
    });
    const element = veil();
    if (element) {
      element.classList.remove("is-visible");
      element.hidden = true;
    }
  }

  document.addEventListener("submit", (event) => {
    const submitter = event.submitter;
    const wantsLoading =
      event.target.hasAttribute("data-loading") ||
      (submitter && submitter.hasAttribute("data-loading"));
    if (!wantsLoading) {
      return;
    }
    if (busy) {
      event.preventDefault();
      return;
    }
    // Keep the submitter enabled so its formaction still applies.
    showLoading(submitter || event.target.querySelector('[type="submit"]'));
  });

  // Coming back via the browser's back button restores a frozen page.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      reset();
    }
  });
})();

// Browser push (PWA). Registers /sw.js, asks permission only on a click, and
// posts the PushSubscription to the server with the CSRF token.
(() => {
  const panel = document.querySelector("[data-push]");
  if (!panel) {
    return;
  }
  const status = panel.querySelector("[data-push-status]");
  const subscribeButton = panel.querySelector("[data-push-subscribe]");
  const unsubscribeButton = panel.querySelector("[data-push-unsubscribe]");
  const iosHint = panel.querySelector("[data-push-ios]");

  const setStatus = (text) => {
    status.textContent = text;
  };
  const csrfToken = () => {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) {
      return decodeURIComponent(match[1]);
    }
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  };
  const keyBytes = (base64url) => {
    const padded = base64url.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (base64url.length % 4)) % 4);
    return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  };
  const deviceLabel = () => {
    const agent = navigator.userAgent;
    const os = /iPhone|iPad/.test(agent) ? "iOS" : /Android/.test(agent) ? "Android" : /Mac/.test(agent) ? "macOS" : /Windows/.test(agent) ? "Windows" : "기기";
    const browser = /Edg\//.test(agent) ? "Edge" : /Firefox\//.test(agent) ? "Firefox" : /Chrome\//.test(agent) ? "Chrome" : /Safari\//.test(agent) ? "Safari" : "브라우저";
    return `${os} ${browser}`;
  };
  const post = (url, body) =>
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(body),
    });

  const isIos = /iPhone|iPad/.test(navigator.userAgent);
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

  if (!supported) {
    if (isIos && !standalone) {
      iosHint.hidden = false;
      setStatus("홈 화면에 추가한 앱에서만 푸시를 켤 수 있습니다.");
    } else {
      setStatus("이 브라우저는 푸시 알림을 지원하지 않습니다.");
    }
    return;
  }

  let registration = null;

  async function refresh() {
    const subscription = await registration.pushManager.getSubscription();
    if (Notification.permission === "denied") {
      setStatus("브라우저 설정에서 이 사이트의 알림이 차단되어 있습니다. 사이트 설정에서 허용으로 바꿔 주세요.");
      subscribeButton.hidden = true;
      unsubscribeButton.hidden = !subscription;
      return subscription;
    }
    subscribeButton.hidden = Boolean(subscription);
    unsubscribeButton.hidden = !subscription;
    setStatus(subscription ? "이 브라우저는 푸시를 받도록 등록되어 있습니다." : "이 브라우저는 아직 등록되지 않았습니다.");
    return subscription;
  }

  async function subscribe() {
    subscribeButton.disabled = true;
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setStatus("알림 권한을 허용해야 푸시를 받을 수 있습니다.");
        return;
      }
      const subscription =
        (await registration.pushManager.getSubscription()) ||
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: keyBytes(panel.dataset.vapidKey),
        }));
      const response = await post(panel.dataset.subscribeUrl, {
        subscription: subscription.toJSON(),
        label: deviceLabel(),
      });
      if (response.ok) {
        window.location.reload();
        return;
      }
      const payload = await response.json().catch(() => ({}));
      setStatus(
        payload.error === "destination_limit"
          ? "알림 대상이 가득 찼습니다. 쓰지 않는 대상을 삭제한 뒤 다시 시도해 주세요."
          : "등록하지 못했습니다. 잠시 후 다시 시도해 주세요."
      );
    } catch (error) {
      setStatus("푸시 등록 중 문제가 생겼습니다. 브라우저 알림 설정을 확인해 주세요.");
    } finally {
      subscribeButton.disabled = false;
    }
  }

  async function unsubscribe() {
    unsubscribeButton.disabled = true;
    try {
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        await post(panel.dataset.unsubscribeUrl, { endpoint: subscription.endpoint });
        await subscription.unsubscribe();
      }
      window.location.reload();
    } catch (error) {
      setStatus("해제하지 못했습니다. 잠시 후 다시 시도해 주세요.");
      unsubscribeButton.disabled = false;
    }
  }

  navigator.serviceWorker
    .register("/sw.js", { scope: "/" })
    .then((result) => {
      registration = result;
      subscribeButton.addEventListener("click", subscribe);
      unsubscribeButton.addEventListener("click", unsubscribe);
      return refresh();
    })
    .catch(() => setStatus("서비스 워커를 등록하지 못했습니다. HTTPS 주소로 접속했는지 확인해 주세요."));
})();

// Alarm editor: add / delete alarm rows (Django inline formset, max 5) and
// dim a row whose on/off switch is off.
(() => {
  const editor = document.querySelector("[data-alarm-editor]");
  if (!editor) {
    return;
  }
  const list = editor.querySelector("[data-alarm-list]");
  const template = editor.querySelector("[data-alarm-template]");
  const addButton = editor.querySelector("[data-alarm-add]");
  const count = editor.querySelector("[data-alarm-count]");
  const total = editor.querySelector('input[name$="-TOTAL_FORMS"]');
  const limit = Number(editor.dataset.alarmLimit || 5);

  const visibleRows = () => [...list.querySelectorAll("[data-alarm-row]")].filter((row) => !row.hidden);

  function refresh() {
    const rows = visibleRows();
    addButton.disabled = rows.length >= limit;
    count.textContent = `${rows.length}/${limit}`;
    rows.forEach((row) => {
      row.querySelector("[data-alarm-delete]").disabled = rows.length <= 1;
      const enabled = row.querySelector('input[name$="-enabled"]');
      row.classList.toggle("is-off", Boolean(enabled && !enabled.checked));
    });
  }

  addButton.addEventListener("click", () => {
    if (visibleRows().length >= limit) {
      return;
    }
    const index = Number(total.value);
    const html = template.innerHTML.replace(/__prefix__/g, String(index));
    list.insertAdjacentHTML("beforeend", html.trim());
    total.value = String(index + 1);
    const row = list.lastElementChild;
    const time = row.querySelector('input[type="time"]');
    if (time) {
      // Start the new alarm on the first free whole hour after the latest one,
      // so an untouched new row never collides with an existing time.
      const taken = new Set(
        visibleRows()
          .filter((other) => other !== row)
          .map((other) => other.querySelector('input[type="time"]').value)
      );
      const latest = [...taken].sort().pop() || "08:00";
      let hour = Number(latest.slice(0, 2));
      for (let step = 0; step < 24; step += 1) {
        hour = (hour + 1) % 24;
        const candidate = `${String(hour).padStart(2, "0")}:00`;
        if (!taken.has(candidate)) {
          time.value = candidate;
          break;
        }
      }
      time.focus();
    }
    refresh();
  });

  list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-alarm-delete]");
    if (!button || visibleRows().length <= 1) {
      return;
    }
    const row = button.closest("[data-alarm-row]");
    const remove = row.querySelector('input[name$="-DELETE"]');
    if (remove) {
      remove.checked = true;
    }
    row.hidden = true;
    refresh();
  });

  list.addEventListener("change", (event) => {
    if (event.target.matches('input[name$="-enabled"]')) {
      refresh();
    }
  });

  refresh();
})();
