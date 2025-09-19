import os, time, jwt
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

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
  <script src="https://webrtc.github.io/adapter/adapter-latest.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"></script>
</head>
<body>
  <h1>PV2 Voice Bot</h1>
  <div class="row">
    <label for="name">Ім'я:</label>
    <input id="name" placeholder="напр., Гість" />
    <button id="join">Join</button>
    <button id="leave" disabled>Leave</button>
    <button id="unmute" style="display:none;">Unmute / Start Audio</button>
  </div>
  <p>Після Join дозволь мікрофон. Агент відповість голосом. (Кімната: pv2-demo.)</p>
  <div id="log"></div>
  <p class="warn" id="hint" style="display:none;"></p>

  <script>
    let room = null;
    let audioCtx = null;

    const logEl  = document.getElementById('log');
    const hintEl = document.getElementById('hint');
    const joinBtn = document.getElementById('join');
    const leaveBtn = document.getElementById('leave');
    const unmuteBtn = document.getElementById('unmute');
    const nameEl = document.getElementById('name');

    const log = (m) => { logEl.textContent += m + "\\n"; logEl.scrollTop = logEl.scrollHeight; };
    const showHint = (msg) => { hintEl.textContent = msg; hintEl.style.display='block'; };

    function appendAudio(track) {
      const el = track.attach();
      el.autoplay = true; el.playsInline = true; el.muted = false; el.volume = 1.0;
      document.body.appendChild(el);
      el.play?.().then(()=>log('audio tag play() ok')).catch(e=>log('audio tag play() fail: ' + e?.message));
    }

    async function unlockAudioPlayback() {
      try {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (AC) {
          if (!audioCtx) audioCtx = new AC();
          if (audioCtx.state === 'suspended') await audioCtx.resume();
          log('AudioContext: ' + audioCtx.state);
        } else {
          log('AudioContext: unavailable');
        }
        if (room && typeof room.startAudio === 'function') {
          const res = await room.startAudio();
          log('room.startAudio() -> ' + res);
        } else {
          log('room.startAudio() not available');
        }
        document.querySelectorAll('audio').forEach(a => {
          a.muted = false; a.volume = 1.0;
          a.play().then(()=>log('audio tag play() ok')).catch(e=>log('audio tag play() fail: ' + e?.message));
        });
        unmuteBtn.style.display = 'none';
        hintEl.style.display = 'none';
      } catch (e) {
        log('unlock error: ' + (e?.message || e));
      }
    }

    async function getToken(roomName, identity) {
      const r = await fetch(`/token?room=${encodeURIComponent(roomName)}&identity=${encodeURIComponent(identity)}`);
      if (!r.ok) throw new Error('token http ' + r.status);
      return r.json();
    }

    async function enableMic(room) {
      const constraints = { echoCancellation:true, noiseSuppression:true, autoGainControl:true };
      const localTrack = await LivekitClient.createLocalAudioTrack(constraints);
      await room.localParticipant.publishTrack(localTrack, { name: 'microphone' });
      log('mic published');
    }

    // --- НОВЕ: примусова підписка на всі аудіо-треки учасника ---
    function subscribeParticipantAudio(p) {
      try {
        log('ensure subscribe for ' + (p.identity || 'unknown'));
        // існуючі публікації
        if (p.tracks && typeof p.tracks.forEach === 'function') {
          p.tracks.forEach(pub => {
            if (pub && pub.kind === 'audio') {
              log('found pub(kind=audio) from ' + (p.identity || '?') + ', subscribed=' + pub.subscribed);
              if (!pub.subscribed) {
                pub.setSubscribed(true).then(()=>log('setSubscribed(true) ok')).catch(e=>log('setSubscribed err: '+(e?.message||e)));
              }
            }
          });
        }
        // нові публікації
        if (typeof p.on === 'function') {
          p.on('trackPublished', (pub) => {
            log('trackPublished from ' + (p.identity||'?') + ' kind=' + pub?.kind);
            if (pub?.kind === 'audio' && !pub.subscribed) {
              pub.setSubscribed(true).then(()=>log('setSubscribed(true) ok (on publish)')).catch(e=>log('setSubscribed err (on publish): '+(e?.message||e)));
            }
          });
        }
      } catch (e) {
        log('subscribeParticipantAudio error: ' + (e?.message || e));
      }
    }

    function wireRoomEvents() {
      room.on('participantConnected', p => {
        log('participant connected: ' + p.identity);
        subscribeParticipantAudio(p);
      });
      room.on('participantDisconnected', p => log('participant disconnected: ' + p.identity));
      room.on('trackSubscribed', (track, pub, participant) => {
        log('track subscribed from ' + (participant.identity||'?') + ' kind=' + (track?.kind));
        if (track?.kind === 'audio') appendAudio(track);
      });
      room.on('audioPlaybackStatusChanged', (playing) => {
        log('audioPlaybackStatusChanged: ' + playing);
        if (!playing) {
          unmuteBtn.style.display = 'inline-block';
          showHint('Натисни "Unmute / Start Audio", щоб увімкнути звук.');
        } else {
          unmuteBtn.style.display = 'none';
          hintEl.style.display = 'none';
        }
      });
      room.on('disconnected', () => log('room disconnected'));
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

        room = new LivekitClient.Room({ adaptiveStream: false, dynacast: false, autoSubscribe: true });
        await room.connect(url, token);
        log('connected as ' + identity + ' to room ' + roomName);

        wireRoomEvents();

        // підписатися на всіх, хто вже в кімнаті (наприклад, pv2-agent)
        try {
          const parts = room.participants;
          if (parts && typeof parts.forEach === 'function') {
            parts.forEach((p, sid) => { log('existing participant: ' + p.identity); subscribeParticipantAudio(p); });
          } else {
            log('participants map not iterable, value: ' + String(parts));
          }
        } catch (e) {
          log('iter participants err: ' + (e?.message || e));
        }

        await enableMic(room);

        // показати кнопку розблокування звуку
        unmuteBtn.style.display = 'inline-block';
        showHint('Браузер міг заблокувати звук. Натисни "Unmute / Start Audio".');
        await unlockAudioPlayback();

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

    unmuteBtn.onclick = async () => {
      await unlockAudioPlayback();
    };
  </script>
</body>
</html>""")

@app.get("/token")
def token(room: str = Query(...), identity: str = Query(...)):
    if not (LK_URL and LK_KEY and LK_SECRET):
        raise HTTPException(500, "LiveKit env not set on server")
    payload = {
        "iss": LK_KEY,
        "sub": identity,
        "name": identity,
        "exp": int(time.time()) + 60*60,
        "video": {"room": room, "roomJoin": True, "canPublish": True, "canSubscribe": True, "canPublishData": True},
    }
    token = jwt.encode(payload, LK_SECRET, algorithm="HS256", headers={"kid": LK_KEY})
    return {"url": LK_URL, "token": token}

@app.get("/health")
def health():
    return {"ok": True}
