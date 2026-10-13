const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("hinana", {
  getSettings: () => ipcRenderer.invoke("settings:get"),
  liveDevices: () => ipcRenderer.invoke('live:devices'),
  liveStatus: () => ipcRenderer.invoke('live:status'),
  liveStart: (request) => ipcRenderer.invoke('live:start', request),
  liveStop: () => ipcRenderer.invoke('live:stop'),
  onLiveEvent: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on('live:event', listener);
    return () => ipcRenderer.removeListener('live:event', listener);
  },
  voiceList: () => ipcRenderer.invoke('voice:list'),
  voiceSelect: () => ipcRenderer.invoke('voice:select'),
  voiceRegister: () => ipcRenderer.invoke('voice:register'),
  createVoiceTarget: () => ipcRenderer.invoke('voice:createTarget'),
  voiceAnalyze: () => ipcRenderer.invoke('voice:analyze'),
  voicePreview: (request) => ipcRenderer.invoke('voice:preview', request),
  voiceSave: (request) => ipcRenderer.invoke('voice:save', request),
  voiceUse: (id) => ipcRenderer.invoke('voice:use', id),
  vocoflexStatus: () => ipcRenderer.invoke('vocoflex:status'),
  launchVocoflex: () => ipcRenderer.invoke('vocoflex:launch'),
  browseVocoflex: () => ipcRenderer.invoke('vocoflex:browse'),
  getAppInfo: () => ipcRenderer.invoke("app:info"),
  saveSettings: (settings) => ipcRenderer.invoke("settings:save", settings),
  openExternal: (url) => ipcRenderer.invoke("external:open", url),
  probe: (settings) => ipcRenderer.invoke("backend:probe", settings),
  sendMessage: (request) => ipcRenderer.invoke("chat:send", request),
  onBackendEvent: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("backend:event", listener);
    return () => ipcRenderer.removeListener("backend:event", listener);
  },
  onOpenAbout: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("about:open", listener);
    return () => ipcRenderer.removeListener("about:open", listener);
  },
});
