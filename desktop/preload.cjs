// Sandboxed preload: exposes one read-only call. No Node APIs reach the page.
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("mdDesktop", Object.freeze({
  session: () => ipcRenderer.invoke("md:session"),
}));
