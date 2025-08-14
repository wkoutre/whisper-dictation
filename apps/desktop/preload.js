const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  load: (opts) => ipcRenderer.invoke('cmd:load', opts),
  start: (opts) => ipcRenderer.invoke('cmd:start', opts),
  stop: () => ipcRenderer.invoke('cmd:stop'),
  status: () => ipcRenderer.invoke('cmd:status'),
  setHotkey: (accelerator, language) => ipcRenderer.invoke('hotkey:set', accelerator, language),
  clearHotkey: () => ipcRenderer.invoke('hotkey:clear'),
  onEvent: (cb) => ipcRenderer.on('server-event', (_e, data) => cb(data))
});

