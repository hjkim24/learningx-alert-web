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

// Shared browser-push helpers (the settings panel and the install banner).
const LXPush = (() => {
  const agent = navigator.userAgent;
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
  // iPadOS reports itself as a Mac; the touch screen gives it away.
  const isIos = /iPhone|iPad|iPod/.test(agent) || (/Macintosh/.test(agent) && navigator.maxTouchPoints > 1);
  const deviceLabel = () => {
    const os = isIos ? "iOS" : /Android/.test(agent) ? "Android" : /Mac/.test(agent) ? "macOS" : /Windows/.test(agent) ? "Windows" : "기기";
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
  const standalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  // Web push on iPhone needs iOS/iPadOS 16.4+ and a home-screen app.
  const iosVersion = () => {
    const match = agent.match(/OS (\d+)_(\d+)/) || agent.match(/Version\/(\d+)\.(\d+)/);
    return match ? [Number(match[1]), Number(match[2])] : [0, 0];
  };
  const iosPushCapable = () => {
    const [major, minor] = iosVersion();
    return major > 16 || (major === 16 && minor >= 4);
  };
  // In-app browsers (KakaoTalk, Instagram, Naver, …) cannot add to home screen.
  const inAppBrowser = () => /KAKAOTALK|NAVER\(inapp|Instagram|FBAN|FBAV|Line\/|DaumApps|everytime|WhaleApp/i.test(agent);
  const isKakao = () => /KAKAOTALK/i.test(agent);
  const register = () => navigator.serviceWorker.register("/sw.js", { scope: "/" });
  // Subscribe this browser and register it with the server. Call it from a
  // click handler: iOS only shows the permission prompt for a user gesture.
  async function subscribe(registration, vapidKey, url, { silent = false } = {}) {
    if (Notification.permission !== "granted") {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        return { ok: false, error: "permission_denied" };
      }
    }
    const subscription =
      (await registration.pushManager.getSubscription()) ||
      (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(vapidKey) }));
    const response = await post(url, { subscription: subscription.toJSON(), label: deviceLabel(), silent });
    const payload = await response.json().catch(() => ({}));
    if (response.ok) {
      return { ok: true, created: Boolean(payload.created), subscription };
    }
    if (payload.error === "subscription_invalid") {
      // Drop the rejected browser subscription so a retry starts clean.
      await subscription.unsubscribe().catch(() => {});
    }
    return { ok: false, error: payload.error || "rejected", subscription };
  }
  return { csrfToken, keyBytes, deviceLabel, post, isIos, standalone, supported, iosPushCapable, inAppBrowser, isKakao, register, subscribe };
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
  const { deviceLabel, post } = LXPush;

  const isIos = LXPush.isIos;
  const standalone = LXPush.standalone();
  const supported = LXPush.supported();

  if (!supported) {
    if (isIos && !standalone) {
      iosHint.hidden = false;
      setStatus("홈 화면에 추가한 앱에서만 푸시를 켤 수 있어요.");
    } else {
      setStatus("이 브라우저는 푸시 알림을 지원하지 않아요.");
    }
    return;
  }

  let registration = null;

  // Tell the server about a subscription the browser already holds. The
  // browser-side subscription alone proves nothing: the server may have
  // rejected it, or the destination may have been deleted since.
  async function syncWithServer(subscription) {
    try {
      const response = await post(panel.dataset.subscribeUrl, {
        subscription: subscription.toJSON(),
        label: deviceLabel(),
        silent: true,
      });
      if (response.ok) {
        const payload = await response.json().catch(() => ({}));
        return payload.created ? "created" : "synced";
      }
      const payload = await response.json().catch(() => ({}));
      return payload.error || "rejected";
    } catch (error) {
      return "offline";
    }
  }

  async function refresh() {
    const subscription = await registration.pushManager.getSubscription();
    if (Notification.permission === "denied") {
      setStatus("이 사이트의 알림이 차단돼 있어요. 브라우저의 사이트 설정에서 허용으로 바꿔 주세요.");
      subscribeButton.hidden = true;
      unsubscribeButton.hidden = !subscription;
      return subscription;
    }
    if (!subscription) {
      subscribeButton.hidden = false;
      unsubscribeButton.hidden = true;
      setStatus("이 브라우저는 아직 등록하지 않았어요.");
      return subscription;
    }
    setStatus("확인하는 중…");
    const result = await syncWithServer(subscription);
    if (result === "created") {
      // Registered just now (e.g. it had been deleted); show it in the list.
      window.location.reload();
      return subscription;
    }
    if (result === "synced") {
      subscribeButton.hidden = true;
      unsubscribeButton.hidden = false;
      setStatus("이 브라우저로 푸시를 받고 있어요.");
      return subscription;
    }
    subscribeButton.hidden = false;
    unsubscribeButton.hidden = false;
    setStatus(
      result === "destination_limit"
        ? "알림 대상이 가득 차서 등록하지 못했어요. 쓰지 않는 대상을 지워 주세요."
        : result === "offline"
          ? "등록 상태를 확인하지 못했어요. 인터넷 연결을 확인하고 새로고침해 주세요."
          : "서버에 등록되지 않았어요. '이 브라우저에서 알림 받기'를 다시 눌러 주세요."
    );
    return subscription;
  }

  async function subscribe() {
    subscribeButton.disabled = true;
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setStatus("알림 권한을 허용해야 푸시를 받을 수 있어요.");
        return;
      }
      const subscription =
        (await registration.pushManager.getSubscription()) ||
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: LXPush.keyBytes(panel.dataset.vapidKey),
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
      if (payload.error === "subscription_invalid") {
        // Drop the rejected browser subscription so a retry starts clean.
        await subscription.unsubscribe().catch(() => {});
      }
      setStatus(
        payload.error === "destination_limit"
          ? "알림 대상이 가득 찼어요. 쓰지 않는 대상을 지우고 다시 시도해 주세요."
          : "등록하지 못했어요. 잠시 후 다시 시도해 주세요."
      );
    } catch (error) {
      setStatus("푸시를 켜지 못했어요. 브라우저 알림 설정을 확인해 주세요.");
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
      setStatus("끄지 못했어요. 잠시 후 다시 시도해 주세요.");
      unsubscribeButton.disabled = false;
    }
  }

  LXPush.register()
    .then((result) => {
      registration = result;
      subscribeButton.addEventListener("click", subscribe);
      unsubscribeButton.addEventListener("click", unsubscribe);
      return refresh();
    })
    .catch(() => setStatus("알림 기능을 준비하지 못했어요. https:// 주소로 접속했는지 확인해 주세요."));
})();

// Install/push banner on signed-in pages. Picks one prompt for this device:
//  - iPhone in an in-app browser (KakaoTalk, …): open in Safari first
//  - iPhone Safari: how to add to the home screen
//  - phone or installed app without push: one "알림 켜기" tap registers it
//  - Android with an install prompt available: "앱으로 설치"
// Desktop browsers get nothing here; the settings page covers them.
(() => {
  const banner = document.querySelector("[data-install-banner]");
  if (!banner) {
    return;
  }
  const DISMISS_KEY = "lx-install-dismissed";
  const DISMISS_MS = 14 * 24 * 60 * 60 * 1000;
  const vapidKey = banner.dataset.vapidKey;
  const subscribeUrl = banner.dataset.subscribeUrl;
  const standalone = LXPush.standalone();
  const recentlyDismissed = (() => {
    try {
      return Date.now() - Number(localStorage.getItem(DISMISS_KEY) || 0) < DISMISS_MS;
    } catch (error) {
      return false;
    }
  })();
  let installEvent = null;
  let pushDone = false;

  const show = (variant) => {
    banner.querySelectorAll("[data-variant]").forEach((element) => {
      element.hidden = element.dataset.variant !== variant;
    });
    banner.hidden = false;
  };
  const hide = () => {
    banner.hidden = true;
  };
  banner.querySelector("[data-install-dismiss]").addEventListener("click", () => {
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch (error) {
      // Private mode: the banner simply comes back next time.
    }
    hide();
  });

  // Android/desktop Chrome: keep the install prompt for our own button.
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installEvent = event;
    banner.querySelectorAll("[data-install-app]").forEach((button) => {
      button.hidden = false;
    });
    if (banner.hidden && pushDone && !recentlyDismissed && /Android/.test(navigator.userAgent)) {
      show("android-install");
    }
  });
  window.addEventListener("appinstalled", () => {
    installEvent = null;
    banner.querySelectorAll("[data-install-app]").forEach((button) => {
      button.hidden = true;
    });
  });
  banner.querySelectorAll("[data-install-app]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!installEvent) {
        return;
      }
      installEvent.prompt();
      await installEvent.userChoice.catch(() => {});
      installEvent = null;
      button.hidden = true;
      if (banner.querySelector('[data-variant="android-install"]:not([hidden])')) {
        hide();
      }
    });
  });

  if (LXPush.isIos && !standalone) {
    if (recentlyDismissed || banner.dataset.hasPush === "1" || !LXPush.iosPushCapable()) {
      return;
    }
    if (LXPush.inAppBrowser()) {
      const external = banner.querySelector("[data-open-external]");
      if (LXPush.isKakao()) {
        external.href = `kakaotalk://web/openExternal?url=${encodeURIComponent(window.location.href)}`;
        external.hidden = false;
      }
      const copyButton = banner.querySelector("[data-copy-link]");
      copyButton.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(window.location.href);
          copyButton.textContent = "복사했어요";
        } catch (error) {
          copyButton.textContent = window.location.host;
        }
      });
      show("ios-inapp");
      return;
    }
    show("ios-add");
    return;
  }

  const mobile = LXPush.isIos || /Android/.test(navigator.userAgent);
  if (!LXPush.supported() || (!standalone && !mobile)) {
    return;
  }

  LXPush.register()
    .then(async (registration) => {
      const existing = await registration.pushManager.getSubscription();
      if (existing) {
        // Make sure the server still has it (it may have been deleted).
        await LXPush.post(subscribeUrl, { subscription: existing.toJSON(), label: LXPush.deviceLabel(), silent: true }).catch(() => {});
        pushDone = true;
        return;
      }
      if (Notification.permission === "denied" || recentlyDismissed) {
        return;
      }
      if (Notification.permission === "granted") {
        // Allowed before (e.g. reinstalled app): register without asking.
        const result = await LXPush.subscribe(registration, vapidKey, subscribeUrl, { silent: true }).catch(() => null);
        if (result && result.ok) {
          pushDone = true;
          return;
        }
      }
      show("enable-push");
      const button = banner.querySelector("[data-enable-push]");
      const message = banner.querySelector("[data-banner-message]");
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const result = await LXPush.subscribe(registration, vapidKey, subscribeUrl);
          if (result.ok) {
            pushDone = true;
            button.hidden = true;
            message.textContent = "이 기기로 알림을 받아요. 알림 설정에서 시험 알림을 보내 볼 수 있어요.";
            window.setTimeout(hide, 6000);
            return;
          }
          message.textContent =
            result.error === "permission_denied"
              ? "알림을 허용하지 않았어요. 기기 설정에서 이 앱의 알림을 켜면 다시 등록할 수 있어요."
              : result.error === "destination_limit"
                ? "알림 대상이 가득 찼어요. 알림 설정에서 쓰지 않는 대상을 지워 주세요."
                : "등록하지 못했어요. 잠시 후 다시 눌러 주세요.";
        } catch (error) {
          message.textContent = "알림을 켜지 못했어요. 잠시 후 다시 눌러 주세요.";
        } finally {
          button.disabled = false;
        }
      });
    })
    .catch(() => {});
})();

// Time picker: replaces the browser's native <input type="time"> popup with a
// themed popover (오전/오후 · 시 · 분). The form still submits one HH:MM value;
// without JS the native input keeps working.
(() => {
  const pad = (number) => String(number).padStart(2, "0");
  const HOURS = Array.from({ length: 12 }, (_, index) => index + 1);
  const MINUTES = Array.from({ length: 60 }, (_, index) => index);
  let openPicker = null;

  function parse(value) {
    const [hours, minutes] = (value || "09:00").split(":").map(Number);
    return {
      period: hours >= 12 ? "pm" : "am",
      hour: hours % 12 === 0 ? 12 : hours % 12,
      minute: Number.isFinite(minutes) ? minutes : 0,
    };
  }

  function format(parts) {
    const base = parts.hour % 12;
    return `${pad(parts.period === "pm" ? base + 12 : base)}:${pad(parts.minute)}`;
  }

  function column(label, name, items, text) {
    const list = document.createElement("div");
    list.className = "time-column";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", label);
    list.dataset.part = name;
    for (const item of items) {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "time-option";
      option.setAttribute("role", "option");
      option.dataset.value = String(item);
      option.textContent = text(item);
      list.appendChild(option);
    }
    return list;
  }

  function sync(input) {
    const field = input.closest(".time-field");
    if (!field) {
      return;
    }
    const parts = parse(input.value);
    field.querySelector(".time-period").textContent = parts.period === "pm" ? "오후" : "오전";
    field.querySelector(".time-digits").textContent = `${pad(parts.hour)}:${pad(parts.minute)}`;
    field.querySelectorAll(".time-column").forEach((list) => {
      const current = String(parts[list.dataset.part]);
      list.querySelectorAll(".time-option").forEach((option) => {
        const selected = option.dataset.value === current;
        option.setAttribute("aria-selected", selected ? "true" : "false");
        option.tabIndex = selected ? 0 : -1;
      });
    });
  }

  function close(field, { focusTrigger = false } = {}) {
    if (!field) {
      return;
    }
    field.querySelector(".time-popover").hidden = true;
    const trigger = field.querySelector(".time-trigger");
    trigger.setAttribute("aria-expanded", "false");
    field.classList.remove("is-open");
    if (openPicker === field) {
      openPicker = null;
    }
    if (focusTrigger) {
      trigger.focus();
    }
  }

  function open(field) {
    if (openPicker && openPicker !== field) {
      close(openPicker);
    }
    const popover = field.querySelector(".time-popover");
    popover.hidden = false;
    field.classList.add("is-open");
    field.querySelector(".time-trigger").setAttribute("aria-expanded", "true");
    openPicker = field;
    popover.querySelectorAll(".time-column").forEach((list) => {
      const selected = list.querySelector('[aria-selected="true"]');
      if (selected) {
        list.scrollTop = selected.offsetTop - (list.clientHeight - selected.offsetHeight) / 2;
      }
    });
    const first = popover.querySelector('[aria-selected="true"]');
    if (first) {
      first.focus({ preventScroll: true });
    }
  }

  function enhance(input) {
    if (!input || input.dataset.enhanced) {
      return;
    }
    input.dataset.enhanced = "true";
    input.type = "hidden";

    const field = document.createElement("span");
    field.className = "time-field";
    input.parentNode.insertBefore(field, input);
    field.appendChild(input);

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "time-trigger";
    trigger.setAttribute("aria-haspopup", "dialog");
    trigger.setAttribute("aria-expanded", "false");
    if (input.id) {
      trigger.id = `${input.id}-trigger`;
      const label = document.querySelector(`label[for="${input.id}"]`);
      if (label) {
        label.htmlFor = trigger.id;
      }
    }
    trigger.innerHTML =
      '<span class="time-period"></span><span class="time-digits"></span>' +
      '<svg class="time-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
      '<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/>' +
      '<path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
    field.appendChild(trigger);

    const popover = document.createElement("div");
    popover.className = "time-popover";
    popover.setAttribute("role", "dialog");
    popover.setAttribute("aria-label", "알림 시각 선택");
    popover.hidden = true;
    const columns = document.createElement("div");
    columns.className = "time-columns";
    columns.append(
      column("오전 또는 오후", "period", ["am", "pm"], (value) => (value === "am" ? "오전" : "오후")),
      column("시", "hour", HOURS, pad),
      column("분", "minute", MINUTES, pad)
    );
    const footer = document.createElement("div");
    footer.className = "time-footer";
    footer.innerHTML = '<button type="button" class="primary-button time-done">완료</button>';
    popover.append(columns, footer);
    field.appendChild(popover);

    trigger.addEventListener("click", () => (popover.hidden ? open(field) : close(field)));

    popover.addEventListener("click", (event) => {
      if (event.target.closest(".time-done")) {
        close(field, { focusTrigger: true });
        return;
      }
      const option = event.target.closest(".time-option");
      if (!option) {
        return;
      }
      const parts = parse(input.value);
      const part = option.closest(".time-column").dataset.part;
      parts[part] = part === "period" ? option.dataset.value : Number(option.dataset.value);
      input.value = format(parts);
      input.dispatchEvent(new Event("change", { bubbles: true }));
      sync(input);
      option.focus({ preventScroll: true });
    });

    popover.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close(field, { focusTrigger: true });
        return;
      }
      const option = event.target.closest(".time-option");
      if (!option || !["ArrowDown", "ArrowUp"].includes(event.key)) {
        return;
      }
      event.preventDefault();
      const sibling = event.key === "ArrowDown" ? option.nextElementSibling : option.previousElementSibling;
      if (sibling) {
        sibling.click();
        sibling.scrollIntoView({ block: "nearest" });
      }
    });

    sync(input);
  }

  document.addEventListener("click", (event) => {
    if (openPicker && !openPicker.contains(event.target)) {
      close(openPicker);
    }
  });

  document.querySelectorAll("[data-alarm-list] .alarm-time-input").forEach(enhance);
  window.lxTimePicker = { enhance, sync };
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
    const time = row.querySelector(".alarm-time-input");
    if (time) {
      // Start the new alarm on the first free whole hour after the latest one,
      // so an untouched new row never collides with an existing time.
      const taken = new Set(
        visibleRows()
          .filter((other) => other !== row)
          .map((other) => other.querySelector(".alarm-time-input").value)
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
      window.lxTimePicker.enhance(time);
      window.lxTimePicker.sync(time);
      const trigger = row.querySelector(".time-trigger");
      (trigger || time).focus();
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

// Save bar: stays hidden until the schedule form differs from what was loaded.
// Reverting every change hides it again; leaving with unsaved edits asks first.
(() => {
  const bar = document.querySelector("[data-save-bar]");
  const form = bar && bar.closest("form");
  if (!form) {
    return;
  }
  const snapshot = () =>
    JSON.stringify(
      [...new FormData(form).entries()]
        .filter(([name]) => name !== "csrfmiddlewaretoken")
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    );
  // A form re-rendered after a failed save already holds unsaved input.
  const startDirty = bar.hasAttribute("data-dirty");
  const initial = snapshot();
  let submitting = false;

  const isDirty = () => startDirty || snapshot() !== initial;
  const refresh = () => bar.toggleAttribute("data-dirty", isDirty());

  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  // Adding or deleting an alarm row changes the form without an input event.
  new MutationObserver(refresh).observe(form, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ["hidden"],
  });
  form.addEventListener("submit", () => {
    submitting = true;
  });
  window.addEventListener("beforeunload", (event) => {
    if (!submitting && isDirty()) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  refresh();
})();

// Preview: "알림 끄기" mutes one item in place (no slow re-query). Without JS the
// form posts normally and lands on the excluded-items page.
(() => {
  const forms = document.querySelectorAll("form[data-exclude]");
  if (!forms.length) {
    return;
  }
  const itemCount = document.querySelector("[data-item-count]");
  const note = document.querySelector("[data-excluded-note]");
  const noteCount = note && note.querySelector("[data-excluded-count]");

  forms.forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button");
      button.disabled = true;
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        if (!response.ok) {
          throw new Error(String(response.status));
        }
        const row = form.closest("[data-preview-item]");
        const group = row.closest(".day-group");
        row.remove();
        if (group && !group.querySelector("[data-preview-item]")) {
          group.remove();
        }
        if (itemCount) {
          itemCount.textContent = String(Math.max(0, Number(itemCount.textContent) - 1));
        }
        if (note && noteCount) {
          noteCount.textContent = String(Number(noteCount.textContent) + 1);
          note.hidden = false;
        }
      } catch (error) {
        button.disabled = false;
        button.textContent = "다시 시도";
      }
    });
  });
})();

// Floating toasts for Django messages: close button, and success/info toasts
// fade out on their own. Errors stay until closed. Hover or focus pauses.
(() => {
  const AUTO_HIDE_MS = 5000;

  function dismiss(toast) {
    if (toast.classList.contains("is-leaving")) return;
    toast.classList.add("is-leaving");
    const remove = () => {
      const stack = toast.parentElement;
      toast.remove();
      if (stack && !stack.children.length) stack.remove();
    };
    toast.addEventListener("transitionend", remove, { once: true });
    setTimeout(remove, 400); // reduced motion: no transitionend
  }

  document.querySelectorAll("[data-toast]").forEach((toast) => {
    toast.querySelector("[data-toast-close]")?.addEventListener("click", () => dismiss(toast));
    if (toast.getAttribute("role") === "alert") return;

    let timer = setTimeout(() => dismiss(toast), AUTO_HIDE_MS);
    const pause = () => clearTimeout(timer);
    const resume = () => {
      clearTimeout(timer);
      timer = setTimeout(() => dismiss(toast), AUTO_HIDE_MS / 2);
    };
    toast.addEventListener("mouseenter", pause);
    toast.addEventListener("focusin", pause);
    toast.addEventListener("mouseleave", resume);
    toast.addEventListener("focusout", resume);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") document.querySelectorAll("[data-toast]").forEach(dismiss);
  });
})();

// Floating feedback button: opens the dialog and posts in place. Without JS
// (or without <dialog> support) the link opens the feedback page instead.
(() => {
  const opener = document.querySelector("[data-feedback-open]");
  const dialog = document.querySelector("[data-feedback-dialog]");
  if (!opener || !dialog || typeof dialog.showModal !== "function") {
    return;
  }
  const form = dialog.querySelector("[data-feedback-form]");
  const fields = dialog.querySelector("[data-feedback-fields]");
  const done = dialog.querySelector("[data-feedback-done]");
  const error = dialog.querySelector("[data-feedback-error]");
  const standalone = dialog.querySelector("[data-feedback-standalone]");
  const submit = form.querySelector("button[type=submit]");

  function reset() {
    form.reset();
    fields.hidden = false;
    done.hidden = true;
    error.hidden = true;
    submit.disabled = false;
  }

  opener.addEventListener("click", (event) => {
    event.preventDefault();
    reset();
    const isStandalone =
      window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
    standalone.value = isStandalone ? "1" : "0";
    dialog.showModal();
    dialog.querySelector("textarea").focus();
  });

  dialog.querySelectorAll("[data-feedback-close]").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      dialog.close(); // backdrop click
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    error.hidden = true;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (response.ok) {
        fields.hidden = true;
        done.hidden = false;
        return;
      }
      error.textContent =
        response.status === 429
          ? "잠시 뒤에 다시 보내 주세요. 10분에 3번까지 보낼 수 있어요."
          : "종류를 고르고 내용을 2,000자 안으로 적어 주세요.";
    } catch (failure) {
      error.textContent = "보내지 못했어요. 연결을 확인하고 다시 시도해 주세요.";
    }
    error.hidden = false;
    submit.disabled = false;
  });
})();

// Canvas connect card: once a school is picked, show only that school's
// "Canvas 설정 열기" button. Without JavaScript every school's button stays.
(() => {
  const choice = document.querySelector("[data-school-choice]");
  if (!choice) return;
  const links = document.querySelectorAll("[data-school-link]");

  function sync() {
    const picked = choice.querySelector('input[name="school"]:checked');
    links.forEach((link) => {
      link.hidden = Boolean(picked) && link.dataset.schoolLink !== picked.value;
    });
  }

  choice.addEventListener("change", sync);
  sync();
})();
