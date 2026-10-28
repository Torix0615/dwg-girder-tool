'use strict';
const { contextBridge, ipcRenderer, webUtils } = require('electron');

const CHANNELS = ['engine-state', 'update-status', 'install-progress', 'feedback-progress'];

contextBridge.exposeInMainWorld('girder', {
  pathOf: (file) => webUtils.getPathForFile(file),
  startJob: () => ipcRenderer.invoke('start-job'),
  run: (paths) => ipcRenderer.invoke('run', paths),
  cancel: () => ipcRenderer.invoke('cancel'),
  removeJob: (id) => ipcRenderer.invoke('remove-job', id),
  engineState: () => ipcRenderer.invoke('engine-state'),
  download: (id, kind) => ipcRenderer.invoke('download', id, kind || 'dxf'),
  openPath: (p) => ipcRenderer.invoke('open-path', p),
  showInFolder: (p) => ipcRenderer.invoke('show-in-folder', p),
  sendFeedback: (payload) => ipcRenderer.invoke('send-feedback', payload),
  openDataFolder: () => ipcRenderer.invoke('open-data-folder'),
  updateCheck: () => ipcRenderer.invoke('update-check'),
  updateStatus: () => ipcRenderer.invoke('update-status'),
  updateInstall: () => ipcRenderer.invoke('update-install'),
  versions: () => ipcRenderer.invoke('versions'),
  getPinned: () => ipcRenderer.invoke('get-pinned'),
  setPinned: (on) => ipcRenderer.invoke('set-pinned', on),
  hide: () => ipcRenderer.invoke('hide-window'),
  on: (channel, cb) => {
    if (!CHANNELS.includes(channel)) return () => {};
    const h = (_e, data) => cb(data);
    ipcRenderer.on(channel, h);
    return () => ipcRenderer.removeListener(channel, h);
  },
});
