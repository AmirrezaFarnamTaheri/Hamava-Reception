"use strict";
const { contextBridge, ipcRenderer } = require("electron");
// Fixed commands only. Never expose raw ipcRenderer, filesystem, Node or shell.
contextBridge.exposeInMainWorld("hamavaNative", Object.freeze({
  getInfo: () => ipcRenderer.invoke("hamava:info"),
  readSession: (options) => ipcRenderer.invoke("hamava:read-session", options),
  writeSession: (options) => ipcRenderer.invoke("hamava:write-session", options),
  clearSession: () => ipcRenderer.invoke("hamava:clear-session"),
  openExternal: (options) => ipcRenderer.invoke("hamava:open-external", options),
}));
