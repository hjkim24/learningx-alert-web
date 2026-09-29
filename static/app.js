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
