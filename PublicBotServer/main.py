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
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; max-width: 780px; margin: 32px auto; padding: 0 16px; }
    label,input,button { font-size: 16px; }
    #log { background:#111; color:#0f0; padding:10px; height:260px; overflow:auto; border-radius:8px; white-space:pre-wrap; }
    .row { display:flex; gap:8px; align-items:center; margin-bottom:12px; }
    input { flex:1; padding:8px; }
    button { padding:8px 14px; }
    .warn { color:#f90; }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap:10px; }
  </style>
  <script src="https://webrtc.github.io/adapter/adapter-latest.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"></script>
</head>
<body>
  <h1>PV2 Voice Bot</h1>

  <div class="grid">
    <div class="row">
      <label style="min-width:70px">Name:</label>
      <input id="name" placeholder="напр., Гість" />
    </div>
    <div class="row">
      <label style="min-width:70px">Room:</label>
      <input id="room" />
      <button id="copy" title="Скопіювати посилання на цю кімнату">Copy invite link</button>
    </div>
  </div>

  <div class="row">
    <button id="join">Join</button>
    <button id="leave" disabled>Leave</button>
    <button id="unmute" style="display:none;">Unmute / Start Audio</button>
    <button id="resub"  style="display:none;">Fix Sound</button>
  </div>

  <p>Після Join дозволь мікрофон. Агент відповість голосом. Рекомендується **своя кімната** (унікальне ім’я), щоб ніхто не заважав.</p>
  <div id="log"></div>
  <p class="warn" id="hint" style="display:none;"></p>

  <script>
    let room = null;
    let audioCtx = null;
    const audioEls = new Set();

    const logEl  = document.getElementById('log');
    const hintEl = document.getElementById('hint');
    const joinBtn = document.getElementById('join');
    const leaveBtn = document.getElementById('leave');
    const unmuteBtn = document.getElementById('unmute');
    const resubBtn  = document.getElementById('resub');
    const nameEl = document.getElementById('name');
    const roomEl = document.getElementById('room');
    const copyBtn = document.getElementById('copy');

    const qs = new URLSearchParams(location.search);
    const defaultRoom = qs.get('room') || ('pv2-' + Math.random().toString(36).slice(2,8));
    roomEl.value = defaultRoom;

    const log = (m) => { logEl.textContent += m + "\\n"; logEl.scrollTop = logEl.scrollHeight; };
    const showHint = (msg) => { hintEl.textContent = msg; hintEl.style.display='block'; };

    function appendAudio(track) {
      const el = track.attach();
      el.autoplay = true; el.playsInline = true; el.muted = false; el.volume = 1.0;
      document.body.appendChild(el);
      audioEls.add(el);
      el.play?.().then(()=>log('audio tag play() ok')).catch(e=>log('audio tag play() fail: ' + e?.message));
    }

    async function unlockAudioPlayback() {
      try {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (AC) {
          if (!audioCtx) audioCtx = new AC();
          if (audioCtx.state === 'suspended') await audioCtx.resume();
          log('AudioContext: ' + audioCtx.state);
        }
        if (room && typeof room.startAudio === 'function') {
          const res = await room.startAudio();
          log('room.startAudio() -> ' + res);
        }
        audioEls.forEach(a => {
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

    // універсальні ітератори (різні версії SDK)
    function listRemoteParticipants() {
      const out = [];
      const cand = room?.participants ?? room?.remoteParticipants ?? null;
      if (!cand) return out;
      if (typeof cand.forEach === 'function') cand.forEach(v => out.push(v));
      else if (typeof cand === 'object') Object.keys(cand).forEach(k => out.push(cand[k]));
      return out;
    }
    function listPublications(p) {
      if (typeof p.getTrackPublications === 'function') return p.getTrackPublications();
      if (p.tracks && typeof p.tracks.forEach === 'function') { const arr=[]; p.tracks.forEach(pub=>arr.push(pub)); return arr; }
      const arr=[]; p.audioTracks?.forEach?.(pub=>arr.push(pub)); p.videoTracks?.forEach?.(pub=>arr.push(pub)); return arr;
    }
    function forceSubscribeAudio(p) {
      const pubs = listPublications(p);
      pubs.forEach(pub => {
        if (pub?.kind === 'audio') {
          log(`pub audio from ${p.identity} subscribed=${pub.subscribed}`);
          if (typeof pub.setSubscribed === 'function' && !pub.subscribed) {
            pub.setSubscribed(true).then(()=>log('setSubscribed(true) ok')).catch(e=>log('setSubscribed err: '+(e?.message||e)));
          }
          const t = pub?.audioTrack || pub?.track;
          if (t && t.kind === 'audio') appendAudio(t);
        }
      });
    }
    function resubAll() { listRemoteParticipants().forEach(p => forceSubscribeAudio(p)); unlockAudioPlayback(); }

    function wireRoomEvents() {
      room.on('participantConnected', p => {
        log('participant connected: ' + p.identity);
        forceSubscribeAudio(p);
        p.on?.('trackPublished', (pub) => {
          log('trackPublished from ' + p.identity + ' kind=' + (pub?.kind));
          if (pub?.kind === 'audio') pub.setSubscribed?.(true).then(()=>log('setSubscribed(true) ok (on publish)')).catch(e=>log('setSubscribed err (on publish): '+(e?.message||e)));
        });
      });
      room.on('participantDisconnected', p => log('participant disconnected: ' + p.identity));
      room.on('trackSubscribed', async (track, pub, participant) => {
        log('track subscribed from ' + (participant?.identity || '?') + ' kind=' + (track?.kind));
        if (track?.kind === 'audio') { appendAudio(track); await unlockAudioPlayback(); }
      });
      room.on('disconnected', () => log('room disconnected'));
    }

    // --- UI кнопки ---
    copyBtn.onclick = async () => {
      const roomName = (roomEl.value || '').trim() || defaultRoom;
      const link = location.origin + '/?room=' + encodeURIComponent(roomName);
      await navigator.clipboard.writeText(link).catch(()=>{});
      log('copied: ' + link);
      alert('Посилання скопійовано: ' + link);
    };

    joinBtn.onclick = async () => {
      try {
        joinBtn.disabled = true;
        const identity = nameEl.value.trim() || ('guest-' + Math.random().toString(36).slice(2));
        const roomName = (roomEl.value || '').trim() || defaultRoom;
        const { url, token } = await getToken(roomName, identity);

        await new Promise(res => {
          if (window.LivekitClient) return res();
          const id = setInterval(() => { if (window.LivekitClient) { clearInterval(id); res(); } }, 50);
          setTimeout(() => { clearInterval(id); res(); }, 2000);
        });

        room = new LivekitClient.Room({ autoSubscribe: true, adaptiveStream: false, dynacast: false });
        await room.connect(url, token);
        log('connected as ' + identity + ' to room ' + roomName);

        wireRoomEvents();

        listRemoteParticipants().forEach(p => { log('existing participant: ' + (p?.identity || '?')); forceSubscribeAudio(p); });

        await enableMic(room);

        unmuteBtn.style.display = 'inline-block';
        resubBtn.style.display  = 'inline-block';
        showHint('Якщо тихо — натисни "Unmute / Start Audio" або "Fix Sound".');
        await unlockAudioPlayback();

        leaveBtn.disabled = false;
      } catch (e) {
        log('ERROR: ' + (e?.message || e));
        joinBtn.disabled = false;
      }
    };

    leaveBtn.onclick = async () => {
      try { leaveBtn.disabled = true; if (room) { await room.disconnect(); room = null; log('left room'); } }
      finally { joinBtn.disabled = false; }
    };
    unmuteBtn.onclick = async () => { await unlockAudioPlayback(); };
    resubBtn.onclick  = () => { resubAll(); };
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
        "video": {
            "room": room, "roomJoin": True,
            "canPublish": True, "canSubscribe": True, "canPublishData": True
        },
    }
    token = jwt.encode(payload, LK_SECRET, algorithm="HS256", headers={"kid": LK_KEY})
    return {"url": LK_URL, "token": token}

@app.get("/health")
def health():
    return {"ok": True}
