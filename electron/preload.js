const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("hinana", {
  getSettings: () => ipcRenderer.invoke("settings:get"),
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
