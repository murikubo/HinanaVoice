const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("hinana", {
  getSettings: () => ipcRenderer.invoke("settings:get"),
  saveSettings: (settings) => ipcRenderer.invoke("settings:save", settings),
  probe: (settings) => ipcRenderer.invoke("backend:probe", settings),
  sendMessage: (request) => ipcRenderer.invoke("chat:send", request),
  onBackendEvent: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("backend:event", listener);
    return () => ipcRenderer.removeListener("backend:event", listener);
  },
});
