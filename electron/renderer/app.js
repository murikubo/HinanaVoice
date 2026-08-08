const $ = (selector) => document.querySelector(selector);

const messages = $("#messages");
const composer = $("#composer");
const messageInput = $("#messageInput");
const sendButton = $("#sendButton");
const status = $("#status");
const settingsDialog = $("#settingsDialog");
const settingsForm = $("#settingsForm");
const settingsMessage = $("#settingsMessage");
const aboutDialog = $("#aboutDialog");

let settings;
let busy = false;
let currentAssistantMeta = null;
let currentAssistantBubble = null;
let currentAssistantArticle = null;
let currentAssistantTranslation = null;

async function openAboutDialog() {
  const info = await window.hinana.getAppInfo();
  $("#aboutProgramName").textContent = info.name.toUpperCase();
  $("#aboutAuthor").textContent = info.author;
  $("#aboutVersion").textContent = `Ver. ${info.version}`;
  aboutDialog.showModal();
}

function appendMessage(role, text, meta = "") {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  article.appendChild(bubble);
  if (meta) {
    const metaElement = document.createElement("div");
    metaElement.className = "message-meta";
    metaElement.textContent = meta;
    article.appendChild(metaElement);
    if (role === "assistant") currentAssistantMeta = metaElement;
  }
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
  if (role === "assistant") {
    currentAssistantArticle = article;
    currentAssistantBubble = bubble;
  }
  return article;
}

function appendAssistantDelta(delta) {
  if (!currentAssistantBubble) {
    appendMessage("assistant", "", "답변을 만들고 있어요…");
  }
  currentAssistantBubble.textContent += delta;
  messages.scrollTop = messages.scrollHeight;
}

function setAssistantTranslation(text, pending = false) {
  if (!currentAssistantArticle) return;
  if (!currentAssistantTranslation) {
    currentAssistantTranslation = document.createElement("p");
    currentAssistantTranslation.className = "translation";
    const meta = currentAssistantArticle.querySelector(".message-meta");
    currentAssistantArticle.insertBefore(currentAssistantTranslation, meta);
  }
  currentAssistantTranslation.classList.toggle("pending", pending);
  currentAssistantTranslation.textContent = text;
  messages.scrollTop = messages.scrollHeight;
}

function setBusy(value) {
  busy = value;
  sendButton.disabled = value;
  messageInput.disabled = value;
  if (!value) messageInput.focus();
}

function resizeInput() {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 150)}px`;
}

function formValues() {
  const selectedDevice = $("#device").selectedOptions[0];
  return {
    voicepeak: $("#voicepeak").value.trim(),
    narrator: $("#narrator").value,
    device: $("#device").value === "" ? null : Number($("#device").value),
    deviceName: selectedDevice?.dataset.name || "",
    deviceApi: selectedDevice?.dataset.api || "",
    speed: Number($("#speed").value),
    pitch: Number($("#pitch").value),
  };
}

function fillSettings(value) {
  $("#voicepeak").value = value.voicepeak;
  $("#speed").value = value.speed;
  $("#pitch").value = value.pitch;
  $("#narrator").dataset.selected = value.narrator;
  $("#device").dataset.selected = value.device ?? "";
  $("#device").dataset.selectedName = value.deviceName || "";
  $("#device").dataset.selectedApi = value.deviceApi || "";
}

async function probe() {
  settingsMessage.className = "settings-message";
  settingsMessage.textContent = "VOICEPEAK와 오디오 장치를 확인하고 있습니다…";
  try {
    const result = await window.hinana.probe(formValues());
    $("#voicepeak").value = result.voicepeak;
    const narrator = $("#narrator");
    const desiredNarrator = narrator.dataset.selected || settings.narrator;
    const narratorNames = result.narrators.length ? result.narrators : [desiredNarrator || "Koharu Rikka"];
    narrator.replaceChildren(...narratorNames.map((name) => new Option(name, name)));
    narrator.value = narratorNames.includes(desiredNarrator) ? desiredNarrator : narratorNames[0];

    const device = $("#device");
    const desiredDevice = Number(device.dataset.selected || settings.device);
    const desiredName = device.dataset.selectedName || settings.deviceName || "";
    const desiredApi = device.dataset.selectedApi || settings.deviceApi || "";
    const virtualDevices = result.devices.filter((item) => item.virtual);
    const shownDevices = virtualDevices.length ? virtualDevices : result.devices;
    const options = shownDevices.map((item) => {
      const option = new Option(`${item.name} · ${item.api}`, String(item.id));
      option.dataset.name = item.name;
      option.dataset.api = item.api;
      return option;
    });
    device.replaceChildren(...options);
    const namedDevice = shownDevices.find(
      (item) => item.name === desiredName && (!desiredApi || item.api === desiredApi),
    );
    const numericDevice = shownDevices.find((item) => item.id === desiredDevice);
    const recommended = [...shownDevices].sort((a, b) => a.priority - b.priority)[0];
    device.value = String(namedDevice?.id ?? numericDevice?.id ?? recommended?.id ?? "");
    settingsMessage.className = result.voicepeakFound ? "settings-message" : "settings-message error";
    settingsMessage.textContent = result.voicepeakFound
      ? `${result.platformName} · 화자 ${result.narrators.length}개 · 가상 출력 ${virtualDevices.length}개`
      : result.voicepeakError;
    $("#routeHelp").textContent = Object.values(result.route).join(" → ");
    status.textContent = result.voicepeakFound ? `${result.platformName} 준비됨` : "VOICEPEAK 설정 필요";
  } catch (error) {
    settingsMessage.className = "settings-message error";
    settingsMessage.textContent = error.message;
    status.textContent = "설정을 확인해 주세요";
  }
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (!text || busy) return;
  if (settings.device === null) {
    settingsDialog.showModal();
    settingsMessage.textContent = "먼저 오디오 출력 장치를 선택해 주세요.";
    return;
  }

  appendMessage("user", text);
  messageInput.value = "";
  resizeInput();
  setBusy(true);
  status.textContent = "전송 중…";
  currentAssistantMeta = null;
  currentAssistantBubble = null;
  currentAssistantArticle = null;
  currentAssistantTranslation = null;

  try {
    await window.hinana.sendMessage({
      ...settings,
      apiKey: $("#apiKey").value.trim(),
      text,
    });
  } catch (error) {
    if (busy) {
      appendMessage("error", error.message || String(error));
      status.textContent = "오류가 발생했습니다";
      setBusy(false);
    }
  }
});

messageInput.addEventListener("input", resizeInput);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

$("#settingsButton").addEventListener("click", () => settingsDialog.showModal());
$("#aboutButton").addEventListener("click", openAboutDialog);
$("#closeAbout").addEventListener("click", () => aboutDialog.close());
$("#githubLink").addEventListener("click", async () => {
  const info = await window.hinana.getAppInfo();
  await window.hinana.openExternal(info.github);
});
window.hinana.onOpenAbout(openAboutDialog);
$("#closeSettings").addEventListener("click", () => settingsDialog.close());
$("#probeButton").addEventListener("click", probe);

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  settings = await window.hinana.saveSettings(formValues());
  settingsDialog.close();
  status.textContent = "설정 저장됨";
  messageInput.focus();
});

window.hinana.onBackendEvent((payload) => {
  if (payload.event === "status") {
    status.textContent = payload.message;
    if (currentAssistantMeta) currentAssistantMeta.textContent = payload.message;
  } else if (payload.event === "answer_delta") {
    appendAssistantDelta(payload.delta);
  } else if (payload.event === "answer_done") {
    if (!currentAssistantBubble) appendMessage("assistant", payload.text);
    else currentAssistantBubble.textContent = payload.text;
    setAssistantTranslation("한국어 번역 중…", true);
  } else if (payload.event === "translation") {
    setAssistantTranslation(payload.text);
  } else if (payload.event === "translation_error") {
    if (currentAssistantTranslation) currentAssistantTranslation.remove();
    currentAssistantTranslation = null;
  } else if (payload.event === "answer") {
    appendMessage("assistant", payload.text, "VOICEPEAK 음성을 준비하고 있어요…");
  } else if (payload.event === "done") {
    status.textContent = "준비됨";
    if (currentAssistantMeta) currentAssistantMeta.textContent = `🔊 ${payload.message}`;
    setBusy(false);
  } else if (payload.event === "error") {
    appendMessage("error", payload.message);
    status.textContent = "오류가 발생했습니다";
    setBusy(false);
  }
});

(async () => {
  settings = await window.hinana.getSettings();
  fillSettings(settings);
  await probe();
  settings = { ...settings, ...formValues() };
  if (!settings.hasEnvironmentKey) settingsDialog.showModal();
  messageInput.focus();
})();
