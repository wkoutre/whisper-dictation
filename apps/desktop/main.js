const { app, BrowserWindow, ipcMain, globalShortcut } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let win;
let py;
let running = false;
let registeredShortcut = null;
let lastProgress = null;
let store;
try {
  const Store = require('electron-store');
  store = new Store({ name: 'settings' });
} catch {
  store = null;
}

function createWindow() {
  win = new BrowserWindow({
    width: 900,
    height: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

function startPython() {
  // Force using the project-local virtual environment's Python
  const fs = require('fs');
  const projectRoot = path.resolve(__dirname, '..', '..');
  const forcedPy = path.join(projectRoot, '.venv', 'bin', 'python');
  if (!fs.existsSync(forcedPy)) {
    win?.webContents.send('server-event', { event: 'stderr', data: `Required interpreter missing: ${forcedPy}. Create it and install deps (python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt) at ${projectRoot}` });
    return;
  }

  // Inform renderer about chosen interpreter
  win?.webContents.send('server-event', { event: 'log', data: `Spawning Python: ${forcedPy} (cwd=${projectRoot})` });

  py = spawn(forcedPy, ['-m', 'whisper_dictation_core.server'], {
    cwd: projectRoot,
    env: process.env,
    stdio: ['pipe', 'pipe', 'pipe']
  });

  py.on('error', (err) => {
    win?.webContents.send('server-event', { event: 'stderr', data: `Failed to spawn python: ${err.message}` });
  });

  py.stdout.setEncoding('utf8');
  py.stdout.on('data', (data) => {
    const lines = data.toString().split(/\r?\n/).filter(Boolean);
    for (const line of lines) {
      try {
        const evt = JSON.parse(line);
        if (evt.event === 'started') running = true;
        if (evt.event === 'stopped') running = false;
        win?.webContents.send('server-event', evt);
      } catch (e) {
        win?.webContents.send('server-event', { event: 'log', data: line });
      }
    }
  });

  py.stderr.on('data', (data) => {
    const text = data.toString();
    // Try to parse percentage like 'Downloading… 45%' or '(45%)'
    const m = text.match(/(\b|\()([0-9]{1,2}|100)%/);
    if (m) {
      const pct = Number(m[2]);
      lastProgress = pct;
      win?.webContents.send('server-event', { event: 'progress', percent: pct, message: text.trim() });
    } else {
      win?.webContents.send('server-event', { event: 'stderr', data: text });
    }
  });

  py.on('close', (code, signal) => {
    win?.webContents.send('server-event', { event: 'exit', code, signal });
  });
}

function sendCmd(cmd, args = {}) {
  const payload = JSON.stringify({ cmd, args }) + '\n';
  if (!py) {
    win?.webContents.send('server-event', { event: 'stderr', data: 'Python server is not running yet.' });
    return;
  }
  try {
    py.stdin.write(payload);
  } catch (e) {
    win?.webContents.send('server-event', { event: 'stderr', data: `Failed to send command: ${e.message}` });
  }
}

app.whenReady().then(async () => {
  createWindow();

  // Start Python only after the renderer is fully loaded to ensure events are received
  win.webContents.once('did-finish-load', () => {
    startPython();

    // Restore settings and notify renderer
    const savedModel = store?.get('model');
    const savedLanguage = store?.get('language');
    const savedHotkey = store?.get('hotkey');
    if (savedModel) win.webContents.send('server-event', { event: 'pref:model', value: savedModel });
    if (savedLanguage) win.webContents.send('server-event', { event: 'pref:language', value: savedLanguage });
    if (savedHotkey) win.webContents.send('server-event', { event: 'pref:hotkey', value: savedHotkey });

    if (savedHotkey && savedLanguage) {
      try {
        const ok = globalShortcut.register(savedHotkey, () => {
          if (running) {
            sendCmd('stop', {});
          } else {
            sendCmd('start', { language: store?.get('language') || 'en' });
          }
        });
        if (ok) registeredShortcut = savedHotkey;
      } catch {}
    }
  });

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') app.quit();
});

ipcMain.handle('cmd:load', (_evt, args) => {
  if (store && args?.model_name) store.set('model', args.model_name);
  sendCmd('load', args);
});
ipcMain.handle('cmd:start', (_evt, args) => {
  if (store && args?.language) store.set('language', args.language);
  sendCmd('start', args);
});
ipcMain.handle('cmd:stop', (_evt) => { sendCmd('stop', {}); });
ipcMain.handle('cmd:status', (_evt) => { sendCmd('status', {}); });

ipcMain.handle('hotkey:set', (_evt, accelerator, language) => {
  try {
    if (registeredShortcut) {
      globalShortcut.unregister(registeredShortcut);
      registeredShortcut = null;
    }
const ok = globalShortcut.register(accelerator, () => {
      if (running) {
        sendCmd('stop', {});
      } else {
        sendCmd('start', { language });
      }
    });
    if (ok) {
      registeredShortcut = accelerator;
      if (store) store.set('hotkey', accelerator);
    }
    return ok;
  } catch (e) {
    return false;
  }
});

ipcMain.handle('hotkey:clear', () => {
  try {
    if (registeredShortcut) {
      globalShortcut.unregister(registeredShortcut);
      registeredShortcut = null;
    }
    if (store) store.delete('hotkey');
    return true;
  } catch (e) {
    return false;
  }
});

