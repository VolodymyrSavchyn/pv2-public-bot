import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from livekit import api as lk_api

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LK_URL = os.getenv("LIVEKIT_URL")
LK_KEY = os.getenv("LIVEKIT_API_KEY")
LK_SECRET = os.getenv("LIVEKIT_API_SECRET")

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse("""<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>PV2 Voice Bot</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; max-width: 720px; margin: 32px auto; padding: 0 16px; }
    label,input,button { font-size: 16px; }
    #log { background:#111; color:#0f0; padding:10px; height:260px; overflow:auto; border-radius:8px; white-space:pre-wrap; }
    .row { display:flex; gap:8px; align-items:center; margin-bottom:12px; }
    input { flex:1; padding:8px; }
    button { padding:8px 14px; }
    .warn { color:#f90; }
  </style>

  <!-- 1) WebRTC shim: додає navigator.mediaDevices.getUserMedia де його нема -->
  <script src="https://webrtc.github.io/adapter/adapter-latest.js"></script>

  <!-- 2) LiveKit UMD (два дзеркала на випадок блокування) -->
  <script src="https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"></script>
  <script>
    if (!window.LivekitClient) {
      var s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/livekit-client/2.15.7/livekit-client.umd.js';
      document.head.appendChild(s);
    }
  </script>
</head>
<body>
  <h1>PV2 Voice Bot</h1>
  <div class="row">
    <label for="name">Ім'я:</label>
    <input id="name" placeholder="напр., Гість" />
    <button id="join">Join</button>
    <button id="leave" disabled>Leave</button>
  </div>
  <p>Після Join дозволь мікрофон. Агент відповість голосом. (Кімната: pv2-demo.)</p>
  <div id="log"></div>
  <p class="warn" id="hint" style="display:none;"></p>

  <script>
    let room = null;

    const logEl  = document.getElementById('log');
    const hintEl = document.getElementById('hint');
    const joinBtn = document.getElementById('join');
    const leaveBtn = document.getElementById('leave');
    const nameEl = document.getElementById('name');

    const log = (m) => { logEl.textContent += m + "\\n"; logEl.scrollTop = logEl.scrollHeight; };
    function showHint(msg){ hintEl.textContent = msg; hintEl.style.display='block'; }

    // діагностика браузера
    function dumpEnv() {
      const n = typeof navigator !== 'undefined' ? navigator : {};
      const md = n.mediaDevices;
      log("diag: has navigator=" + !!navigator
        + ", mediaDevices=" + !!md
        + ", getUserMedia=" + !!(md && md.getUserMedia)
        + ", legacy=" + !!(n.getUserMedia || n.webkitGetUserMedia || n.mozGetUserMedia));
    }

    const appendAudio = (track) => {
      const el = track.attach(); el.autoplay = true; el.playsInline = true;
      document.body.appendChild(el);
    };

    async function getToken(roomName, identity) {
      const r = await fetch(`/token?room=${encodeURIComponent(roomName)}&identity=${encodeURIComponent(identity)}`);
      if (!r.ok) throw new Error('token http ' + r.status);
      return r.json();
    }

    async function enableMicUniversal(room) {
      // 1) офіційний шлях LiveKit
      try {
        await new Promise(res => {
          if (window.LivekitClient) return res();
          const id = setInterval(() => { if (window.LivekitClient) { clearInterval(id); res(); } }, 50);
          setTimeout(() => { clearInterval(id); res(); }, 2000);
        });
        const constraints = { echoCancellation:true, noiseSuppression:true, autoGainControl:true };
        const localTrack = await LivekitClient.createLocalAudioTrack(constraints);
        await room.localParticipant.publishTrack(localTrack, { name: 'microphone' });
        log('microphone published (createLocalAudioTrack)');
        return;
      } catch (e) {
        log('WARN: createLocalAudioTrack failed: ' + (e?.message || e));
      }

      // 2) фолбек через getUserMedia (після adapter.js має зʼявитися)
      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          throw new Error('getUserMedia not available');
        }
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const [audioTrack] = stream.getAudioTracks();
        if (!audioTrack) throw new Error('no audio track from getUserMedia');
        await room.localParticipant.publishTrack(audioTrack, { name: 'microphone' });
        log('microphone published (fallback gUM)');
        return;
      } catch (e) {
        log('ERROR: gUM fallback failed: ' + (e?.message || e));
        showHint('Схоже, у цьому браузері вимкнено WebRTC API. Спробуй Chrome/Firefox/Edge або iOS Safari, і обовʼязково відкривай через HTTPS (на публічному домені).');
        dumpEnv();
        throw e;
      }
    }

    joinBtn.onclick = async () => {
      try {
        joinBtn.disabled = true;
        const identity = nameEl.value.trim() || ('guest-' + Math.random().toString(16).slice(2));
        const roomName = new URLSearchParams(location.search).get('room') || 'pv2-demo';

        const { url, token } = await getToken(roomName, identity);

        await new Promise(res => {
          if (window.LivekitClient) return res();
          const id = setInterval(() => { if (window.LivekitClient) { clearInterval(id); res(); } }, 50);
          setTimeout(() => { clearInterval(id); res(); }, 2000);
        });

        room = new LivekitClient.Room();
        await room.connect(url, token);
        log('connected as ' + identity + ' to room ' + roomName);

        await enableMicUniversal(room);

        room.on('participantConnected', p => log('participant connected: ' + p.identity));
        room.on('participantDisconnected', p => log('participant disconnected: ' + p.identity));
        room.on('trackSubscribed', (track, pub, participant) => {
          log('track subscribed from ' + participant.identity);
          if (track.kind === 'audio') appendAudio(track);
        });
        room.on('disconnected', () => log('room disconnected'));

        leaveBtn.disabled = false;
      } catch (e) {
        log('ERROR: ' + (e && e.message ? e.message : e));
        joinBtn.disabled = false;
      }
    };

    leaveBtn.onclick = async () => {
      try {
        leaveBtn.disabled = true;
        if (room) { await room.disconnect(); room = null; log('left room'); }
      } finally {
        joinBtn.disabled = false;
      }
    };
  </script>
</body>
</html>""")

@app.get("/token")
def token(room: str = Query(...), identity: str = Query(...)):
    if not (LK_URL and LK_KEY and LK_SECRET):
        raise HTTPException(500, "LiveKit env not set on server")
    grants = lk_api.VideoGrants(room_join=True, room=room)
    at = lk_api.AccessToken(LK_KEY, LK_SECRET).with_identity(identity).with_name(identity).with_grants(grants)
    return {"url": LK_URL, "token": at.to_jwt()}

@app.get("/health")
def health():
    return {"ok": True}
