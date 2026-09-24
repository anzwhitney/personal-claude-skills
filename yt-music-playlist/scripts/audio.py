"""Audio-content analysis for the yt-music-playlist skill.

Optional layer on top of ytm.py: fetches a track's audio by videoId (via
yt-dlp), derives a compact set of features with Essentia (signal-processing
measures plus small pretrained TF models), caches the features by videoId,
and deletes the audio. Only derived numbers are ever kept.

Requires requirements-audio.txt (essentia-tensorflow, yt-dlp) in the shared
venv. Nothing here is imported by the base skill unless audio analysis is
requested, and audio_unavailable_reason() lets callers degrade gracefully
when the dependencies aren't installed.

Feature dict (one per videoId, see analyze()):
  voice_frac   share of ~2s model frames classified as voice (>0.5)
  voice_mean   mean voice probability across frames
  voice_segments   [[start_s, end_s], ...] where voice is detected (gaps up
               to VOICE_MERGE_GAP_SECONDS merged). Present on analyses made
               since it was added; re-run with --refresh to backfill a track.
  relaxed, sad, aggressive, danceable   mean class probabilities (0-1)
  arousal, valence   emomusic regression (1-9 scale)
  lufs, lra    EBU R128 integrated loudness / loudness range
  loud_start, loud_end   75th-percentile short-term LUFS over the first /
               last 30s (the level a listener hears at the edges, ignoring
               the very tail of a fade)
  loud_contour 10-point short-term LUFS contour across the track
  onset_rate   note/event onsets per second (textural density)
  bpm, bpm_conf   tempo and RhythmExtractor2013 confidence (0-5.32;
               below ~1.5 the bpm is unreliable, common for ambient)
  key, scale, key_strength
  styles       top Discogs styles, e.g. [["Electronic/Ambient", 0.62], ...]
  duration, source ("full"), analyzer_version, label ("Artist - Title")
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from ytm import STATE_DIR, ensure_state_dir

ANALYZER_VERSION = 2

MODELS_DIR = STATE_DIR / "models"
AUDIO_TMP_DIR = STATE_DIR / "audio-tmp"
FEATURES_CACHE_FILE = STATE_DIR / "audio-features.json"
EMBEDDINGS_CACHE_FILE = STATE_DIR / "audio-embeddings.json"

MODEL_BASE_URL = "https://essentia.upf.edu/models"
MODELS = {
    "discogs-effnet-bs64-1.pb": (
        "feature-extractors/discogs-effnet",
        "3ed9af50d5367c0b9c795b294b00e7599e4943244f4cbd376869f3bfc87721b1"),
    "voice_instrumental-discogs-effnet-1.pb": (
        "classification-heads/voice_instrumental",
        "c8033548e17c292874265db62e82a051247768d10375a35a769e7bf695f16acf"),
    "mood_relaxed-discogs-effnet-1.pb": (
        "classification-heads/mood_relaxed",
        "2c5aa6666b58fe80429a2dc677a135e9995922889b5a399af87d1c15f0ebb71d"),
    "mood_sad-discogs-effnet-1.pb": (
        "classification-heads/mood_sad",
        "4865cba49968b6ec295db3e8af6b4a7bb506b1a646628b9f07ee9910d52df82c"),
    "mood_aggressive-discogs-effnet-1.pb": (
        "classification-heads/mood_aggressive",
        "7705284e3a67f23f04d3f2fd75e18a82c0e70db8875b7b6f7061f2432de80858"),
    "danceability-discogs-effnet-1.pb": (
        "classification-heads/danceability",
        "e1251f02cdc846445e2bc1fb3fe9963e32728c5c000e009188ae47c8963cb4c4"),
    "genre_discogs400-discogs-effnet-1.pb": (
        "classification-heads/genre_discogs400",
        "3885ba078a35249af94b8e5e4247689afac40deca4401a4bc888daf5a579c01c"),
    "genre_discogs400-discogs-effnet-1.json": (
        "classification-heads/genre_discogs400",
        "2d367319d9b782ffa10f69abf0e805b3ac4e10899025e5bdbaceda3919b243e0"),
    "msd-musicnn-1.pb": (
        "feature-extractors/musicnn",
        "cdea0722bcee7f731286843f2233e3aa69887bb5c3e2dce011eff55f38d04f3e"),
    "emomusic-msd-musicnn-2.pb": (
        "classification-heads/emomusic",
        "fcfb486510213b35e0a691975325f58170f648ad4a02d749bce790da13ded43b"),
}

# (model file, index of the class whose probability we report, feature name).
# Class orders come from each model's published metadata JSON.
EFFNET_HEADS = [
    ("voice_instrumental-discogs-effnet-1.pb", 1, "voice"),       # [instrumental, voice]
    ("mood_relaxed-discogs-effnet-1.pb", 1, "relaxed"),           # [non_relaxed, relaxed]
    ("mood_sad-discogs-effnet-1.pb", 1, "sad"),                   # [non_sad, sad]
    ("mood_aggressive-discogs-effnet-1.pb", 0, "aggressive"),     # [aggressive, not_aggressive]
    ("danceability-discogs-effnet-1.pb", 0, "danceable"),         # [danceable, not_danceable]
]

TOP_STYLES = 5

# TensorflowPredictEffnetDiscogs' default patch hop (62 mel frames of 256
# samples at 16kHz); each frame's prediction covers ~2s from its start.
EFFNET_FRAME_HOP_SECONDS = 62 * 256 / 16000
EFFNET_FRAME_SPAN_SECONDS = 128 * 256 / 16000
VOICE_MERGE_GAP_SECONDS = 4

EDGE_WINDOW_SECONDS = 30
SHORT_TERM_HOP_SECONDS = 0.1  # LoudnessEBUR128's default hopSize
SILENCE_LUFS = -70.0

# YouTube Music turns tracks louder than this down to it during playback
# (quieter tracks are not boosted), so perceived loudness at a transition is
# the analyzed level minus that attenuation.
DEFAULT_PLAYBACK_NORMALIZATION_LUFS = -14.0


def audio_unavailable_reason() -> str | None:
    """None if audio analysis can run, else a one-line reason why not."""
    missing = []
    for mod in ("essentia", "yt_dlp", "numpy"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return (f"audio analysis unavailable (missing {', '.join(missing)}; "
                f"install yt-music-playlist/requirements-audio.txt into the shared venv)")
    return None


# --- Caches (diff-friendly: sorted keys, one track per line) ---

def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.exists() else {}


def _save_per_line(path: Path, data: dict[str, Any]) -> None:
    ensure_state_dir()
    lines = [f"{json.dumps(k)}: {json.dumps(data[k], sort_keys=True, ensure_ascii=False)}"
             for k in sorted(data)]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("{\n" + ",\n".join(lines) + "\n}\n")
    tmp.replace(path)


def load_features_cache() -> dict[str, dict[str, Any]]:
    return _load_json(FEATURES_CACHE_FILE)


def cached_features(video_id: str) -> dict[str, Any] | None:
    f = load_features_cache().get(video_id)
    if f and f.get("analyzer_version") == ANALYZER_VERSION:
        return f
    return None


def load_vectors(video_id: str) -> dict[str, Any] | None:
    """A track's cached similarity vectors: "effnet" (1280-d mean embedding)
    and "styles" (400 Discogs style activations)."""
    import numpy as np

    raw = _load_json(EMBEDDINGS_CACHE_FILE).get(video_id)
    if not isinstance(raw, dict):
        return None
    return {k: np.frombuffer(base64.b64decode(v), dtype=np.float16).astype(np.float32) for k, v in raw.items()}


def _store(video_id: str, features: dict[str, Any], vectors: dict[str, Any]) -> None:
    import numpy as np

    cache = load_features_cache()
    cache[video_id] = features
    _save_per_line(FEATURES_CACHE_FILE, cache)
    embs = _load_json(EMBEDDINGS_CACHE_FILE)
    embs[video_id] = {k: base64.b64encode(np.asarray(v, dtype=np.float16).tobytes()).decode()
                      for k, v in vectors.items()}
    _save_per_line(EMBEDDINGS_CACHE_FILE, embs)


# --- Models and audio fetching ---

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_models() -> None:
    """Download any missing model files and verify their checksums."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name, (subdir, digest) in MODELS.items():
        dest = MODELS_DIR / name
        if dest.exists() and _sha256(dest) == digest:
            continue
        url = f"{MODEL_BASE_URL}/{subdir}/{name}"
        print(f"  downloading model {name} ...")
        tmp = dest.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out)
        if _sha256(tmp) != digest:
            tmp.unlink()
            raise RuntimeError(f"checksum mismatch for model {name} from {url}")
        tmp.replace(dest)


class _QuietLogger:
    """Swallow yt-dlp's own output; failures surface as the raised exception."""

    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def fetch_audio(video_id: str, dest_dir: Path, attempts: int = 3) -> Path:
    """Download a track's best audio-only stream (m4a preferred) into dest_dir.
    YouTube intermittently answers a stream request with 403 (a retry of the
    same request usually succeeds), so failures are retried with backoff."""
    import yt_dlp

    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),
    }
    try:
        from deno import find_deno_bin  # the pip-installed deno yt-dlp needs for YouTube
        opts["js_runtimes"] = {"deno": {"path": find_deno_bin()}}
    except ImportError:
        pass
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://music.youtube.com/watch?v={video_id}", download=True)
                return Path(ydl.prepare_filename(info))
        except yt_dlp.utils.DownloadError as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise last_exc


# --- Analysis ---

class Analyzer:
    """Holds the loaded Essentia models; build one per process and reuse it,
    since loading the TF graphs costs a few seconds."""

    def __init__(self) -> None:
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        import essentia

        essentia.log.infoActive = False
        essentia.log.warningActive = False
        import essentia.standard as es

        ensure_models()
        self.es = es
        m = lambda name: str(MODELS_DIR / name)  # noqa: E731
        self.effnet = es.TensorflowPredictEffnetDiscogs(
            graphFilename=m("discogs-effnet-bs64-1.pb"), output="PartitionedCall:1")
        self.heads = [
            (es.TensorflowPredict2D(graphFilename=m(f), output="model/Softmax"), idx, name)
            for f, idx, name in EFFNET_HEADS
        ]
        self.styles = es.TensorflowPredict2D(
            graphFilename=m("genre_discogs400-discogs-effnet-1.pb"),
            input="serving_default_model_Placeholder", output="PartitionedCall:0")
        meta = json.loads((MODELS_DIR / "genre_discogs400-discogs-effnet-1.json").read_text())
        self.style_names = [c.replace("---", "/") for c in meta["classes"]]
        self.musicnn = es.TensorflowPredictMusiCNN(
            graphFilename=m("msd-musicnn-1.pb"), output="model/dense/BiasAdd")
        self.emomusic = es.TensorflowPredict2D(
            graphFilename=m("emomusic-msd-musicnn-2.pb"), output="model/Identity")

    def analyze_file(self, path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (features, similarity vectors) for an audio file."""
        import numpy as np

        es = self.es
        audio16 = es.MonoLoader(filename=str(path), sampleRate=16000, resampleQuality=4)()
        stereo, sr, *_ = es.AudioLoader(filename=str(path))()
        mono = stereo.mean(axis=1)

        emb = self.effnet(audio16)
        feats: dict[str, Any] = {}
        for head, idx, name in self.heads:
            probs = head(emb)[:, idx]
            if name == "voice":
                feats["voice_frac"] = round(float((probs > 0.5).mean()), 3)
                feats["voice_mean"] = round(float(probs.mean()), 3)
                feats["voice_segments"] = _voice_segments(probs > 0.5, len(audio16) / 16000)
            else:
                feats[name] = round(float(probs.mean()), 3)

        style_act = self.styles(emb).mean(axis=0)
        top = np.argsort(style_act)[::-1][:TOP_STYLES]
        feats["styles"] = [[self.style_names[i], round(float(style_act[i]), 2)] for i in top]

        valence, arousal = self.emomusic(self.musicnn(audio16)).mean(axis=0)
        feats["valence"] = round(float(valence), 2)
        feats["arousal"] = round(float(arousal), 2)

        _, short_term, integrated, lra = es.LoudnessEBUR128(sampleRate=sr)(stereo)
        st = np.asarray(short_term, dtype=float)
        feats["lufs"] = round(float(integrated), 1)
        feats["lra"] = round(float(lra), 1)
        edge = int(EDGE_WINDOW_SECONDS / SHORT_TERM_HOP_SECONDS)
        feats["loud_start"] = _edge_level(st[:edge])
        feats["loud_end"] = _edge_level(st[-edge:])
        feats["loud_contour"] = [_edge_level(chunk, pct=50) for chunk in np.array_split(st, 10)]

        feats["onset_rate"] = round(float(es.OnsetRate()(mono)[1]), 2)

        bpm, _, bpm_conf, *_ = es.RhythmExtractor2013(method="multifeature")(mono)
        feats["bpm"] = round(float(bpm), 1)
        feats["bpm_conf"] = round(float(bpm_conf), 2)

        key, scale, strength = es.KeyExtractor()(mono)
        feats.update(key=key, scale=scale, key_strength=round(float(strength), 2))

        feats["duration"] = int(round(len(mono) / sr))
        return feats, {"effnet": emb.mean(axis=0), "styles": style_act}

    def analyze(self, video_id: str, label: str | None = None, refresh: bool = False) -> dict[str, Any]:
        """Cached features for a videoId, fetching and analyzing on a miss.
        Raises on download/decode failure; callers decide how to report it."""
        if not refresh:
            cached = cached_features(video_id)
            if cached:
                return cached
        AUDIO_TMP_DIR.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=AUDIO_TMP_DIR))
        try:
            feats, vectors = self.analyze_file(fetch_audio(video_id, tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        feats.update(source="full", analyzer_version=ANALYZER_VERSION)
        if label:
            feats["label"] = label
        _store(video_id, feats, vectors)
        return feats


class FeatureSource:
    """Cache-first feature lookup that only loads the models (a few seconds)
    on the first cache miss. get() never raises: failures come back as
    (None, reason) so callers can report the track as unanalyzed."""

    def __init__(self, refresh: bool = False) -> None:
        self.refresh = refresh
        self._analyzer: Analyzer | None = None

    def get(self, video_id: str, label: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
        if not self.refresh:
            cached = cached_features(video_id)
            if cached:
                return cached, None
        try:
            if self._analyzer is None:
                self._analyzer = Analyzer()
            return self._analyzer.analyze(video_id, label, refresh=self.refresh), None
        except Exception as exc:  # noqa: BLE001 - reported per track, never fatal
            return None, f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"


def _voice_segments(voiced, duration: float) -> list[list[int]]:
    """Merge per-frame voice detections into [start, end] second ranges."""
    segments: list[list[float]] = []
    for i, on in enumerate(voiced):
        if not on:
            continue
        start = i * EFFNET_FRAME_HOP_SECONDS
        end = min(start + EFFNET_FRAME_SPAN_SECONDS, duration)
        if segments and start - segments[-1][1] <= VOICE_MERGE_GAP_SECONDS:
            segments[-1][1] = end
        else:
            segments.append([start, end])
    return [[int(a), int(round(b))] for a, b in segments]


def _edge_level(values, pct: int = 75) -> float | None:
    import numpy as np

    v = np.asarray(values, dtype=float)
    v = v[v > SILENCE_LUFS]
    return round(float(np.percentile(v, pct)), 1) if v.size else None


# --- Comparisons (shared by analyze_tracks.py and build_playlist.py) ---

_CAMELOT_MINOR = ["G#", "D#", "A#", "F", "C", "G", "D", "A", "E", "B", "F#", "C#"]
_CAMELOT_MAJOR = ["B", "F#", "C#", "G#", "D#", "A#", "F", "C", "G", "D", "A", "E"]
_ENHARMONIC = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}


def camelot(feats: dict[str, Any]) -> str | None:
    """Camelot wheel code (e.g. '8A') for a track's detected key."""
    key = _ENHARMONIC.get(feats.get("key"), feats.get("key"))
    wheel = _CAMELOT_MINOR if feats.get("scale") == "minor" else _CAMELOT_MAJOR
    if key not in wheel:
        return None
    return f"{wheel.index(key) + 1}{'A' if feats.get('scale') == 'minor' else 'B'}"


def key_distance(a: dict[str, Any], b: dict[str, Any]) -> int | None:
    """Steps on the Camelot wheel (0 = same key, 1 = harmonically adjacent)."""
    ca, cb = camelot(a), camelot(b)
    if not ca or not cb:
        return None
    na, nb = int(ca[:-1]), int(cb[:-1])
    step = min((na - nb) % 12, (nb - na) % 12)
    return step + (ca[-1] != cb[-1])


def tempo_ratio(a: dict[str, Any], b: dict[str, Any], min_conf: float = 1.5) -> float | None:
    """Tempo ratio (>= 1) after folding out half/double-time, or None if
    either track's tempo estimate is too unreliable to compare."""
    if (a.get("bpm_conf") or 0) < min_conf or (b.get("bpm_conf") or 0) < min_conf:
        return None
    if not a.get("bpm") or not b.get("bpm"):
        return None
    r = b["bpm"] / a["bpm"]
    r /= 2 ** round(math.log2(r))
    return round(max(r, 1 / r), 3)


def playback_level(feats: dict[str, Any], field: str, normalization: float | None) -> float | None:
    """A loudness field adjusted for the player's loudness normalization."""
    level = feats.get(field)
    if level is None or normalization is None or feats.get("lufs") is None:
        return level
    return round(level - max(0.0, feats["lufs"] - normalization), 1)


def transition(a: dict[str, Any], b: dict[str, Any],
               normalization: float | None = DEFAULT_PLAYBACK_NORMALIZATION_LUFS,
               min_bpm_conf: float = 1.5) -> dict[str, Any]:
    """Metrics for playing track a then track b.

    loudness_rise_lu is how far b's opening sits above a's overall playback
    level. Measured against a's whole-track level rather than its last
    seconds, because a quiet fade-out followed by a normal start is not
    jarring, and drops into a quiet intro are routine in hand-curated
    sessions; a track that opens clearly louder than what came before is."""
    prev, start = playback_level(a, "lufs", normalization), playback_level(b, "loud_start", normalization)
    return {
        "loudness_rise_lu": None if prev is None or start is None else round(start - prev, 1),
        "arousal_delta": round(b["arousal"] - a["arousal"], 2),
        "tempo_ratio": tempo_ratio(a, b, min_bpm_conf),
        "key_distance": key_distance(a, b),
    }


def style_similarity(video_id_a: str, video_id_b: str) -> float | None:
    """Cosine similarity of two tracks' Discogs style activations -- the
    basis that best matched listening judgments in testing (raw effnet
    embeddings rated nearly everything ~0.7 alike)."""
    va, vb = load_vectors(video_id_a), load_vectors(video_id_b)
    if not va or not vb:
        return None
    return round(cosine_similarity(va["styles"], vb["styles"]), 3)


def cosine_similarity(u, v) -> float:
    import numpy as np

    return float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))


def summary_columns(feats: dict[str, Any] | None) -> str:
    """Compact fixed-width audio summary for tables and timelines."""
    if not feats:
        return f"{'(unanalyzed)':<44}"
    bpm = f"{feats['bpm']:.0f}" + ("" if (feats.get("bpm_conf") or 0) >= 1.5 else "?")
    loud = f"{_fmt_db(feats.get('loud_start'))}>{_fmt_db(feats.get('loud_end'))}"
    return (f"voc{feats['voice_frac'] * 100:3.0f}% ar{feats['arousal']:4.1f} "
            f"rlx{feats['relaxed']:4.2f} {feats['lufs']:5.1f}LU {loud:>7} "
            f"{bpm:>4}bpm {camelot(feats) or '?':>3} {short_styles(feats):<22}")


def short_styles(feats: dict[str, Any], n: int = 2) -> str:
    return ",".join(name.split("/")[-1] for name, _ in (feats.get("styles") or [])[:n])


def _fmt_db(v: float | None) -> str:
    return "?" if v is None else f"{v:.0f}"
