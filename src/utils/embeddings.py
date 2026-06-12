"""Embeddings + similarity search (Phase C of the analysis program).

Text vectors over clip/shot summaries and transcript segments, CLIP image
vectors over sampled frames, CLAP audio vectors over per-shot audio windows.
Backends are detected, never installed (the whisper pattern):

- text: ollama serving ``nomic-embed-text`` (preferred — works on Apple
  Silicon via Metal), or ``sentence_transformers`` when installed.
- visual: ``open_clip_torch`` (ViT-B-32) when installed alongside torch.
- audio: ``transformers`` ClapModel (laion/clap-htsat-unfused; preferred) or
  ``laion_clap`` when installed alongside torch; needs ffmpeg. Audio windows
  are piped from the source media as raw PCM — read-only, no temp files.

Vectors live in the per-project DB (schema v10 ``embeddings`` table) as
float32 BLOBs, one row per (entity, kind, model). Similarity is brute-force
cosine — numpy when present, pure Python otherwise; this is thousands of
vectors, not millions. Embedding is local compute, so nothing here touches
the vision-token caps ledger; responses report wall-clock + counts instead.
"""

from __future__ import annotations

import array
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.utils import timeline_brain_db

OLLAMA_URL = os.environ.get("DAVINCI_RESOLVE_MCP_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_TEXT_MODEL = os.environ.get("DAVINCI_RESOLVE_MCP_EMBED_MODEL", "nomic-embed-text")
SENTENCE_TRANSFORMERS_MODEL = "all-MiniLM-L6-v2"
OPEN_CLIP_MODEL = ("ViT-B-32", "laion2b_s34b_b79k")

CLAP_HF_MODEL = "laion/clap-htsat-unfused"
CLAP_SAMPLE_RATE = 48000
AUDIO_WINDOW_SECONDS = 10.0  # CLAP works on ~10s windows; longer shots are center-cropped

_PROBE_TIMEOUT_SECONDS = 2.0
_EMBED_TIMEOUT_SECONDS = 120.0

# Lazy singletons for heavyweight local models.
_ST_MODEL = None
_CLIP_STATE: Optional[Tuple[Any, Any, Any]] = None  # (model, preprocess, torch)
_CLAP_STATE: Optional[Tuple[str, Any]] = None  # (backend, state)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def pack_vector(vector: Sequence[float]) -> bytes:
    return array.array("f", vector).tobytes()


def unpack_vector(blob: bytes) -> List[float]:
    arr = array.array("f")
    arr.frombytes(blob)
    return list(arr)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    try:
        import numpy as np

        va, vb = np.asarray(a, dtype="float32"), np.asarray(b, dtype="float32")
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        if denom == 0.0:
            return 0.0
        return float(np.dot(va, vb) / denom)
    except ImportError:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)


# ── backend detection (no installs, ever) ────────────────────────────────────


def _ollama_state() -> Dict[str, Any]:
    binary = shutil.which("ollama")
    state: Dict[str, Any] = {
        "binary": binary,
        "serving": False,
        "model_present": False,
        "model": OLLAMA_TEXT_MODEL,
    }
    if not binary:
        return state
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=_PROBE_TIMEOUT_SECONDS) as resp:
            payload = json.load(resp)
        state["serving"] = True
        models = [str(m.get("name") or "") for m in payload.get("models") or []]
        state["model_present"] = any(
            name == OLLAMA_TEXT_MODEL or name.startswith(f"{OLLAMA_TEXT_MODEL}:")
            for name in models
        )
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        pass
    return state


def detect_embedding_capabilities() -> Dict[str, Any]:
    """Availability of text/visual embedding backends, with install guidance."""
    ollama = _ollama_state()
    st_available = importlib.util.find_spec("sentence_transformers") is not None
    torch_available = importlib.util.find_spec("torch") is not None
    open_clip_available = importlib.util.find_spec("open_clip") is not None

    text_backends = []
    if ollama["binary"] and ollama["serving"] and ollama["model_present"]:
        text_backends.append("ollama")
    if st_available:
        text_backends.append("sentence_transformers")

    guidance: Dict[str, str] = {}
    if not text_backends:
        if ollama["binary"] and ollama["serving"] and not ollama["model_present"]:
            guidance["text"] = f"Ask the user before running: ollama pull {OLLAMA_TEXT_MODEL}"
        elif ollama["binary"] and not ollama["serving"]:
            guidance["text"] = f"Start ollama (ollama serve), then: ollama pull {OLLAMA_TEXT_MODEL}"
        else:
            guidance["text"] = (
                f"Install ollama (https://ollama.com) and pull {OLLAMA_TEXT_MODEL}, "
                "or pip install sentence-transformers."
            )
    visual_available = torch_available and open_clip_available
    if not visual_available:
        guidance["visual"] = (
            "pip install open_clip_torch"
            if torch_available
            else "pip install torch open_clip_torch"
        )

    transformers_available = importlib.util.find_spec("transformers") is not None
    laion_clap_available = importlib.util.find_spec("laion_clap") is not None
    ffmpeg_available = bool(shutil.which("ffmpeg"))
    audio_backends: List[str] = []
    if torch_available and ffmpeg_available:
        if transformers_available:
            audio_backends.append("transformers_clap")
        if laion_clap_available:
            audio_backends.append("laion_clap")
    if not audio_backends:
        if not ffmpeg_available:
            guidance["audio"] = "Install ffmpeg (audio windows are extracted with it)."
        else:
            guidance["audio"] = (
                "pip install transformers (CLAP via laion/clap-htsat-unfused), "
                "or pip install laion_clap"
                if torch_available
                else "pip install torch transformers"
            )

    return {
        "success": True,
        "no_auto_install": True,
        "text": {
            "available": bool(text_backends),
            "backends": text_backends,
            "ollama": ollama,
            "model": OLLAMA_TEXT_MODEL if "ollama" in text_backends else (
                SENTENCE_TRANSFORMERS_MODEL if st_available else None
            ),
        },
        "visual": {
            "available": visual_available,
            "backends": ["open_clip"] if visual_available else [],
            "model": "-".join(OPEN_CLIP_MODEL) if visual_available else None,
        },
        "audio": {
            "available": bool(audio_backends),
            "backends": audio_backends,
            "model": CLAP_HF_MODEL if audio_backends else None,
            "ffmpeg": ffmpeg_available,
        },
        "install_guidance": guidance,
    }


# ── embedding calls ──────────────────────────────────────────────────────────


def _embed_texts_ollama(texts: List[str]) -> Tuple[List[List[float]], str]:
    body = json.dumps({"model": OLLAMA_TEXT_MODEL, "input": texts}).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/embed",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=_EMBED_TIMEOUT_SECONDS) as resp:
        payload = json.load(resp)
    vectors = payload.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise ValueError(f"ollama returned {len(vectors or [])} embeddings for {len(texts)} inputs")
    return vectors, f"ollama:{OLLAMA_TEXT_MODEL}"


def _embed_texts_sentence_transformers(texts: List[str]) -> Tuple[List[List[float]], str]:
    global _ST_MODEL
    if _ST_MODEL is None:
        from sentence_transformers import SentenceTransformer

        _ST_MODEL = SentenceTransformer(SENTENCE_TRANSFORMERS_MODEL)
    vectors = _ST_MODEL.encode(texts, convert_to_numpy=True)
    return [list(map(float, v)) for v in vectors], f"sentence_transformers:{SENTENCE_TRANSFORMERS_MODEL}"


def embed_texts(texts: List[str], *, backend: Optional[str] = None) -> Dict[str, Any]:
    """Embed a batch of texts with the best available local backend."""
    if not texts:
        return {"success": True, "vectors": [], "model": None}
    caps = detect_embedding_capabilities()
    backends = caps["text"]["backends"]
    chosen = backend or (backends[0] if backends else None)
    if chosen not in backends:
        return {
            "success": False,
            "error": "No text-embedding backend available",
            "install_guidance": caps["install_guidance"].get("text"),
        }
    try:
        if chosen == "ollama":
            vectors, model = _embed_texts_ollama(texts)
        else:
            vectors, model = _embed_texts_sentence_transformers(texts)
    except Exception as exc:  # noqa: BLE001 — backend failures surface as data
        return {"success": False, "error": f"{type(exc).__name__}: {exc}", "backend": chosen}
    return {"success": True, "vectors": vectors, "model": model, "backend": chosen}


def _clip_model():
    global _CLIP_STATE
    if _CLIP_STATE is None:
        import open_clip
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms(
            OPEN_CLIP_MODEL[0], pretrained=OPEN_CLIP_MODEL[1]
        )
        model.eval()
        _CLIP_STATE = (model, preprocess, torch)
    return _CLIP_STATE


def embed_images(paths: List[str]) -> Dict[str, Any]:
    """Embed image files with open_clip. Skips missing files."""
    caps = detect_embedding_capabilities()
    if not caps["visual"]["available"]:
        return {
            "success": False,
            "error": "No visual-embedding backend available",
            "install_guidance": caps["install_guidance"].get("visual"),
        }
    try:
        from PIL import Image

        model, preprocess, torch = _clip_model()
        vectors: List[Optional[List[float]]] = []
        with torch.no_grad():
            for path in paths:
                if not path or not os.path.isfile(path):
                    vectors.append(None)
                    continue
                image = preprocess(Image.open(path).convert("RGB")).unsqueeze(0)
                features = model.encode_image(image)
                features = features / features.norm(dim=-1, keepdim=True)
                vectors.append([float(x) for x in features[0].tolist()])
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"success": True, "vectors": vectors, "model": f"open_clip:{'-'.join(OPEN_CLIP_MODEL)}"}


def embed_text_for_visual_query(text: str) -> Dict[str, Any]:
    """CLIP text encoder — lets a free-text query search visual vectors."""
    caps = detect_embedding_capabilities()
    if not caps["visual"]["available"]:
        return {
            "success": False,
            "error": "No visual-embedding backend available",
            "install_guidance": caps["install_guidance"].get("visual"),
        }
    try:
        import open_clip

        model, _preprocess, torch = _clip_model()
        tokenizer = open_clip.get_tokenizer(OPEN_CLIP_MODEL[0])
        with torch.no_grad():
            features = model.encode_text(tokenizer([text]))
            features = features / features.norm(dim=-1, keepdim=True)
        return {
            "success": True,
            "vector": [float(x) for x in features[0].tolist()],
            "model": f"open_clip:{'-'.join(OPEN_CLIP_MODEL)}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


# ── audio (CLAP) ─────────────────────────────────────────────────────────────


def _clap_state() -> Tuple[str, Any]:
    """Lazy-load the preferred CLAP backend: transformers (HF-cached, kept
    current) over the laion_clap package."""
    global _CLAP_STATE
    if _CLAP_STATE is None:
        caps = detect_embedding_capabilities()["audio"]
        backends = caps["backends"]
        if "transformers_clap" in backends:
            from transformers import ClapModel, ClapProcessor

            model = ClapModel.from_pretrained(CLAP_HF_MODEL)
            model.eval()
            processor = ClapProcessor.from_pretrained(CLAP_HF_MODEL)
            _CLAP_STATE = ("transformers_clap", (model, processor))
        elif "laion_clap" in backends:
            import laion_clap

            module = laion_clap.CLAP_Module(enable_fusion=False)
            module.load_ckpt()  # default pretrained checkpoint
            _CLAP_STATE = ("laion_clap", module)
        else:
            raise RuntimeError("No audio-embedding backend available")
    return _CLAP_STATE


def _extract_audio_window(file_path: str, start_seconds: float, duration_seconds: float):
    """Mono 48 kHz float32 samples piped straight from ffmpeg — read-only on
    the source media, no temp files. Returns None when the window is empty
    (e.g. video-only media)."""
    import subprocess

    import numpy as np

    command = [
        "ffmpeg", "-v", "error",
        "-ss", f"{max(0.0, float(start_seconds)):.3f}",
        "-t", f"{max(0.1, float(duration_seconds)):.3f}",
        "-i", file_path,
        "-vn", "-ac", "1", "-ar", str(CLAP_SAMPLE_RATE),
        "-f", "f32le", "-",
    ]
    try:
        proc = subprocess.run(command, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    samples = np.frombuffer(proc.stdout, dtype=np.float32)
    return samples if samples.size else None


def _clap_audio_vectors(waveforms: List[Any]) -> Tuple[List[List[float]], str]:
    backend, state = _clap_state()
    if backend == "transformers_clap":
        import torch

        model, processor = state
        inputs = processor(audios=waveforms, sampling_rate=CLAP_SAMPLE_RATE, return_tensors="pt", padding=True)
        with torch.no_grad():
            features = model.get_audio_features(**inputs)
            features = features / features.norm(dim=-1, keepdim=True)
        return [[float(x) for x in row.tolist()] for row in features], f"transformers_clap:{CLAP_HF_MODEL}"
    import numpy as np

    module = state
    vectors = module.get_audio_embedding_from_data(x=np.stack(waveforms), use_tensor=False)
    return [[float(x) for x in row] for row in vectors], "laion_clap:default"


def embed_audio_windows(file_path: str, windows: List[Tuple[float, float]]) -> Dict[str, Any]:
    """Embed (start_seconds, end_seconds) windows of one media file with CLAP.

    Windows longer than AUDIO_WINDOW_SECONDS are center-cropped. Vector slots
    are None for windows with no decodable audio.
    """
    caps = detect_embedding_capabilities()
    if not caps["audio"]["available"]:
        return {
            "success": False,
            "error": "No audio-embedding backend available",
            "install_guidance": caps["install_guidance"].get("audio"),
        }
    if not os.path.isfile(file_path):
        return {"success": False, "error": f"media not found: {file_path}"}
    waveforms: List[Any] = []
    slots: List[Optional[int]] = []
    for start, end in windows:
        duration = max(0.1, float(end) - float(start))
        if duration > AUDIO_WINDOW_SECONDS:
            start = float(start) + (duration - AUDIO_WINDOW_SECONDS) / 2.0
            duration = AUDIO_WINDOW_SECONDS
        samples = _extract_audio_window(file_path, float(start), duration)
        if samples is None:
            slots.append(None)
            continue
        slots.append(len(waveforms))
        waveforms.append(samples)
    if not waveforms:
        return {"success": True, "vectors": [None] * len(windows), "model": None,
                "note": "no decodable audio in any window"}
    try:
        vectors, model = _clap_audio_vectors(waveforms)
    except Exception as exc:  # noqa: BLE001 — backend failures surface as data
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "success": True,
        "vectors": [vectors[slot] if slot is not None else None for slot in slots],
        "model": model,
    }


def embed_text_for_audio_query(text: str) -> Dict[str, Any]:
    """CLAP text encoder — lets a free-text query ('engine revving') search
    audio vectors."""
    caps = detect_embedding_capabilities()
    if not caps["audio"]["available"]:
        return {
            "success": False,
            "error": "No audio-embedding backend available",
            "install_guidance": caps["install_guidance"].get("audio"),
        }
    try:
        backend, state = _clap_state()
        if backend == "transformers_clap":
            import torch

            model, processor = state
            inputs = processor(text=[str(text)], return_tensors="pt", padding=True)
            with torch.no_grad():
                features = model.get_text_features(**inputs)
                features = features / features.norm(dim=-1, keepdim=True)
            return {"success": True, "vector": [float(x) for x in features[0].tolist()],
                    "model": f"transformers_clap:{CLAP_HF_MODEL}"}
        vectors = state.get_text_embedding([str(text), ""], use_tensor=False)
        return {"success": True, "vector": [float(x) for x in vectors[0]], "model": "laion_clap:default"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


# ── content builders ─────────────────────────────────────────────────────────


def _shot_embed_text(shot: Dict[str, Any]) -> str:
    parts: List[str] = []
    if shot.get("description"):
        parts.append(str(shot["description"]))
    extra = shot.get("extra_json")
    if extra:
        try:
            groups = json.loads(extra)
        except (TypeError, ValueError):
            groups = {}
        for group in ("visual", "content", "editorial", "cuttability", "production"):
            block = groups.get(group)
            if isinstance(block, dict):
                for key, value in sorted(block.items()):
                    if value in (None, "", [], {}):
                        continue
                    parts.append(f"{key}: {json.dumps(value, sort_keys=True, default=str)}")
    return "\n".join(parts).strip()


def _clip_embed_text(clip: Dict[str, Any], conn: sqlite3.Connection) -> str:
    parts: List[str] = []
    for key in ("clip_name", "summary"):
        if clip.get(key):
            parts.append(str(clip[key]))
    row = conn.execute(
        """
        SELECT value_json FROM subjective_fields
        WHERE entity_type='clip' AND entity_uuid=? AND field_path='clip_summary'
          AND superseded_at IS NULL
        """,
        (clip["clip_uuid"],),
    ).fetchone()
    if row:
        try:
            parts.append(str(json.loads(row["value_json"])))
        except (TypeError, ValueError):
            pass
    tags = conn.execute(
        """
        SELECT value_json FROM subjective_fields
        WHERE entity_type='clip' AND entity_uuid=? AND field_path='editing_notes.search_tags'
          AND superseded_at IS NULL
        """,
        (clip["clip_uuid"],),
    ).fetchone()
    if tags:
        try:
            parts.append("tags: " + ", ".join(map(str, json.loads(tags["value_json"]) or [])))
        except (TypeError, ValueError):
            pass
    return "\n".join(parts).strip()


# ── build ────────────────────────────────────────────────────────────────────


def _existing_rows(conn: sqlite3.Connection, kind: str) -> Dict[Tuple[str, str], str]:
    rows = conn.execute(
        "SELECT entity_type, entity_uuid, content_hash FROM embeddings WHERE embedding_kind = ?",
        (kind,),
    ).fetchall()
    return {(str(r["entity_type"]), str(r["entity_uuid"])): str(r["content_hash"] or "") for r in rows}


def _store_vectors(
    project_root: str,
    kind: str,
    model: str,
    items: List[Tuple[str, str, str, List[float]]],
) -> int:
    """items: (entity_type, entity_uuid, content_hash, vector)."""
    if not items:
        return 0
    now = _now()
    with timeline_brain_db.transaction(project_root) as conn:
        for entity_type, entity_uuid, content_hash, vector in items:
            conn.execute(
                """
                INSERT INTO embeddings
                    (entity_type, entity_uuid, embedding_kind, model_name,
                     dimension, vector, content_hash, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_type, entity_uuid, embedding_kind, model_name)
                DO UPDATE SET vector=excluded.vector, dimension=excluded.dimension,
                              content_hash=excluded.content_hash, computed_at=excluded.computed_at
                """,
                (entity_type, entity_uuid, kind, model, len(vector), pack_vector(vector), content_hash, now),
            )
    return len(items)


def build_embeddings(
    project_root: str,
    *,
    kinds: Sequence[str] = ("text",),
    clip_ref: Any = None,
    include_segments: bool = True,
    max_frames_per_clip: int = 16,
) -> Dict[str, Any]:
    """Build/refresh embeddings for a project (or one clip). Idempotent:
    entities whose content hash is unchanged are skipped."""
    from src.utils import analysis_store

    started = time.time()
    conn = timeline_brain_db.connect(project_root)
    clip_filter: Optional[str] = None
    if clip_ref:
        clip_filter = analysis_store.resolve_clip_uuid(conn, clip_ref)
        if not clip_filter:
            return {"success": False, "error": f"clip not found in DB: {clip_ref!r} (run db_ingest first)"}

    result: Dict[str, Any] = {"success": True, "project_root": project_root, "kinds": list(kinds)}
    where = " WHERE clip_uuid = ?" if clip_filter else ""
    args: Tuple[Any, ...] = (clip_filter,) if clip_filter else ()

    if "text" in kinds:
        texts: List[str] = []
        meta: List[Tuple[str, str, str]] = []  # (entity_type, uuid, hash)
        existing = _existing_rows(conn, "text")
        for clip in conn.execute(f"SELECT * FROM clips{where}", args).fetchall():
            clip = dict(clip)
            text = _clip_embed_text(clip, conn)
            if text:
                h = _content_hash(text)
                if existing.get(("clip", clip["clip_uuid"])) != h:
                    texts.append(text)
                    meta.append(("clip", clip["clip_uuid"], h))
        for shot in conn.execute(
            f"SELECT * FROM shots{where} ORDER BY clip_uuid, shot_index", args
        ).fetchall():
            shot = dict(shot)
            text = _shot_embed_text(shot)
            if text:
                h = _content_hash(text)
                if existing.get(("shot", shot["shot_uuid"])) != h:
                    texts.append(text)
                    meta.append(("shot", shot["shot_uuid"], h))
        if include_segments:
            for seg in conn.execute(
                f"SELECT * FROM transcript_segments{where} ORDER BY clip_uuid, segment_index", args
            ).fetchall():
                seg = dict(seg)
                text = str(seg.get("text") or "").strip()
                if len(text) < 8:
                    continue
                uuid = f"{seg['clip_uuid']}:{seg['segment_index']}"
                h = _content_hash(text)
                if existing.get(("segment", uuid)) != h:
                    texts.append(text)
                    meta.append(("segment", uuid, h))
        if texts:
            embedded = embed_texts(texts)
            if not embedded.get("success"):
                result["text"] = embedded
                result["success"] = False
                return result
            stored = _store_vectors(
                project_root,
                "text",
                str(embedded["model"]),
                [(m[0], m[1], m[2], v) for m, v in zip(meta, embedded["vectors"])],
            )
            result["text"] = {"success": True, "embedded": stored, "skipped_unchanged": None, "model": embedded["model"]}
        else:
            result["text"] = {"success": True, "embedded": 0, "note": "all up to date"}

    if "visual" in kinds:
        existing = _existing_rows(conn, "visual")
        frame_rows = conn.execute(
            f"SELECT * FROM frames{where} ORDER BY clip_uuid, frame_index", args
        ).fetchall()
        by_clip: Dict[str, List[Dict[str, Any]]] = {}
        for row in frame_rows:
            by_clip.setdefault(str(row["clip_uuid"]), []).append(dict(row))
        paths: List[str] = []
        meta_v: List[Tuple[str, str, str]] = []
        frame_shot: List[Optional[str]] = []
        for clip_uuid, rows in by_clip.items():
            on_disk = [r for r in rows if r.get("frame_path") and os.path.isfile(str(r["frame_path"]))]
            if len(on_disk) > max_frames_per_clip:
                step = len(on_disk) / float(max_frames_per_clip)
                on_disk = [on_disk[int(i * step)] for i in range(max_frames_per_clip)]
            for r in on_disk:
                uuid = f"{clip_uuid}:{r['frame_index']}"
                h = _content_hash(str(r["frame_path"]))
                if existing.get(("frame", uuid)) == h:
                    continue
                paths.append(str(r["frame_path"]))
                meta_v.append(("frame", uuid, h))
                frame_shot.append(str(r["shot_uuid"]) if r.get("shot_uuid") else None)
        if paths:
            embedded = embed_images(paths)
            if not embedded.get("success"):
                result["visual"] = embedded
                result["success"] = False
                return result
            items = []
            shot_acc: Dict[str, List[List[float]]] = {}
            for m, shot_uuid, vector in zip(meta_v, frame_shot, embedded["vectors"]):
                if vector is None:
                    continue
                items.append((m[0], m[1], m[2], vector))
                if shot_uuid:
                    shot_acc.setdefault(shot_uuid, []).append(vector)
            # Per-shot visual vector = mean of its frames'.
            for shot_uuid, vectors in shot_acc.items():
                dim = len(vectors[0])
                mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
                items.append(("shot", shot_uuid, _content_hash(json.dumps(sorted(len(v) for v in vectors)) + shot_uuid), mean))
            stored = _store_vectors(project_root, "visual", str(embedded["model"]), items)
            result["visual"] = {"success": True, "embedded": stored, "model": embedded["model"]}
        else:
            result["visual"] = {"success": True, "embedded": 0, "note": "all up to date"}

    if "audio" in kinds:
        caps = detect_embedding_capabilities()
        if not caps["audio"]["available"]:
            result["audio"] = {
                "success": False,
                "skipped": True,
                "error": "No audio-embedding backend available",
                "install_guidance": caps["install_guidance"].get("audio"),
            }
            result["success"] = False
            return result
        existing = _existing_rows(conn, "audio")
        embedded_count = 0
        missing_media: List[str] = []
        audio_model: Optional[str] = None
        for clip in conn.execute(f"SELECT * FROM clips{where}", args).fetchall():
            clip = dict(clip)
            file_path = str(clip.get("file_path") or "")
            if not file_path or not os.path.isfile(file_path):
                missing_media.append(str(clip.get("clip_name") or clip["clip_uuid"]))
                continue
            shots = [dict(s) for s in conn.execute(
                "SELECT shot_uuid, time_seconds_start, time_seconds_end FROM shots "
                "WHERE clip_uuid = ? ORDER BY shot_index",
                (clip["clip_uuid"],),
            ).fetchall()]
            windows: List[Tuple[float, float]] = []
            window_meta: List[Tuple[str, str, str]] = []
            for shot in shots:
                start, end = shot.get("time_seconds_start"), shot.get("time_seconds_end")
                if start is None or end is None or float(end) - float(start) < 0.2:
                    continue
                h = _content_hash(f"{file_path}|{start}|{end}")
                if existing.get(("shot", str(shot["shot_uuid"]))) == h:
                    continue
                windows.append((float(start), float(end)))
                window_meta.append(("shot", str(shot["shot_uuid"]), h))
            if not windows:
                continue
            embedded = embed_audio_windows(file_path, windows)
            if not embedded.get("success"):
                result["audio"] = embedded
                result["success"] = False
                return result
            if not embedded.get("model"):
                continue  # no decodable audio in this clip (e.g. video-only)
            audio_model = str(embedded["model"])
            items: List[Tuple[str, str, str, List[float]]] = []
            clip_vectors: List[List[float]] = []
            for m, vector in zip(window_meta, embedded["vectors"]):
                if vector is None:
                    continue
                items.append((m[0], m[1], m[2], vector))
                clip_vectors.append(vector)
            # Clip-level audio vector = mean of its shot windows' (the
            # per-shot-visual pattern).
            if clip_vectors:
                dim = len(clip_vectors[0])
                mean = [sum(v[i] for v in clip_vectors) / len(clip_vectors) for i in range(dim)]
                items.append((
                    "clip", str(clip["clip_uuid"]),
                    _content_hash(f"{file_path}|clip|{len(clip_vectors)}"), mean,
                ))
            embedded_count += _store_vectors(project_root, "audio", audio_model, items)
        result["audio"] = {
            "success": True,
            "embedded": embedded_count,
            "model": audio_model,
            **({"skipped_missing_media": missing_media} if missing_media else {}),
            **({"note": "all up to date"} if not embedded_count and not missing_media else {}),
        }

    result["wall_clock_ms"] = int((time.time() - started) * 1000)
    counts = conn.execute(
        "SELECT embedding_kind, COUNT(*) AS n FROM embeddings GROUP BY embedding_kind"
    ).fetchall()
    result["totals"] = {str(r["embedding_kind"]): int(r["n"]) for r in counts}
    return result


# ── similarity search ────────────────────────────────────────────────────────


def _hydrate(conn: sqlite3.Connection, entity_type: str, entity_uuid: str) -> Dict[str, Any]:
    if entity_type == "clip":
        row = conn.execute(
            "SELECT clip_uuid, clip_name, clip_dir, summary FROM clips WHERE clip_uuid = ?",
            (entity_uuid,),
        ).fetchone()
        return dict(row) if row else {}
    if entity_type == "shot":
        row = conn.execute(
            """
            SELECT s.shot_uuid, s.clip_uuid, s.shot_index, s.time_seconds_start,
                   s.time_seconds_end, s.description, c.clip_name
            FROM shots s LEFT JOIN clips c ON c.clip_uuid = s.clip_uuid
            WHERE s.shot_uuid = ?
            """,
            (entity_uuid,),
        ).fetchone()
        return dict(row) if row else {}
    if entity_type == "segment":
        clip_uuid, _, seg_index = entity_uuid.rpartition(":")
        row = conn.execute(
            """
            SELECT t.clip_uuid, t.segment_index, t.start_seconds, t.end_seconds,
                   t.text, c.clip_name
            FROM transcript_segments t LEFT JOIN clips c ON c.clip_uuid = t.clip_uuid
            WHERE t.clip_uuid = ? AND t.segment_index = ?
            """,
            (clip_uuid, int(seg_index) if seg_index.isdigit() else -1),
        ).fetchone()
        return dict(row) if row else {}
    if entity_type == "frame":
        clip_uuid, _, frame_index = entity_uuid.rpartition(":")
        row = conn.execute(
            """
            SELECT f.clip_uuid, f.frame_index, f.time_seconds, f.frame_path,
                   f.shot_uuid, c.clip_name
            FROM frames f LEFT JOIN clips c ON c.clip_uuid = f.clip_uuid
            WHERE f.clip_uuid = ? AND f.frame_index = ?
            """,
            (clip_uuid, int(frame_index) if frame_index.lstrip("-").isdigit() else -1),
        ).fetchone()
        return dict(row) if row else {}
    return {}


def find_similar(
    project_root: str,
    *,
    text: Optional[str] = None,
    clip_ref: Any = None,
    shot_index: Optional[int] = None,
    shot_uuid: Optional[str] = None,
    kind: str = "text",
    entity_types: Optional[Sequence[str]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Brute-force cosine search. Query by free text, a clip, or a shot."""
    from src.utils import analysis_store

    conn = timeline_brain_db.connect(project_root)
    kind = (kind or "text").strip().lower()
    if kind not in ("text", "visual", "audio"):
        return {"success": False, "error": f"kind must be 'text', 'visual', or 'audio', got {kind!r}"}

    exclude: Optional[Tuple[str, str]] = None
    query_vector: Optional[List[float]] = None
    query_model: Optional[str] = None

    if text:
        if kind == "text":
            embedded = embed_texts([str(text)])
            if not embedded.get("success"):
                return embedded
            query_vector = embedded["vectors"][0]
            query_model = str(embedded["model"])
        elif kind == "audio":
            encoded = embed_text_for_audio_query(str(text))
            if not encoded.get("success"):
                return encoded
            query_vector = encoded["vector"]
            query_model = str(encoded["model"])
        else:
            encoded = embed_text_for_visual_query(str(text))
            if not encoded.get("success"):
                return encoded
            query_vector = encoded["vector"]
            query_model = str(encoded["model"])
    else:
        entity_type: Optional[str] = None
        entity_uuid: Optional[str] = None
        if shot_uuid:
            entity_type, entity_uuid = "shot", str(shot_uuid)
        elif clip_ref is not None and shot_index is not None:
            clip_uuid = analysis_store.resolve_clip_uuid(conn, clip_ref)
            if not clip_uuid:
                return {"success": False, "error": f"clip not found in DB: {clip_ref!r}"}
            row = conn.execute(
                "SELECT shot_uuid FROM shots WHERE clip_uuid = ? AND shot_index = ?",
                (clip_uuid, int(shot_index)),
            ).fetchone()
            if not row:
                return {"success": False, "error": f"shot_index {shot_index} not found"}
            entity_type, entity_uuid = "shot", str(row["shot_uuid"])
        elif clip_ref is not None:
            clip_uuid = analysis_store.resolve_clip_uuid(conn, clip_ref)
            if not clip_uuid:
                return {"success": False, "error": f"clip not found in DB: {clip_ref!r}"}
            entity_type, entity_uuid = "clip", clip_uuid
        else:
            return {"success": False, "error": "find_similar requires text, clip_id/clip_dir, or shot"}
        row = conn.execute(
            """
            SELECT vector, model_name FROM embeddings
            WHERE entity_type = ? AND entity_uuid = ? AND embedding_kind = ?
            """,
            (entity_type, entity_uuid, kind),
        ).fetchone()
        if not row:
            return {
                "success": False,
                "error": (
                    f"No {kind} embedding for that {entity_type} yet — run "
                    "media_analysis(action='build_embeddings') first."
                ),
            }
        query_vector = unpack_vector(row["vector"])
        query_model = str(row["model_name"])
        exclude = (entity_type, entity_uuid)

    where = "embedding_kind = ? AND model_name = ?"
    args: List[Any] = [kind, query_model]
    if entity_types:
        placeholders = ",".join("?" for _ in entity_types)
        where += f" AND entity_type IN ({placeholders})"
        args.extend(entity_types)
    rows = conn.execute(
        f"SELECT entity_type, entity_uuid, vector FROM embeddings WHERE {where}", args
    ).fetchall()

    scored: List[Tuple[float, str, str]] = []
    for row in rows:
        key = (str(row["entity_type"]), str(row["entity_uuid"]))
        if exclude and key == exclude:
            continue
        score = cosine_similarity(query_vector, unpack_vector(row["vector"]))
        scored.append((score, key[0], key[1]))
    scored.sort(key=lambda item: item[0], reverse=True)

    results = []
    for score, entity_type, entity_uuid in scored[: max(1, int(limit))]:
        entry = {
            "score": round(score, 4),
            "entity_type": entity_type,
            "entity_uuid": entity_uuid,
        }
        entry.update(_hydrate(conn, entity_type, entity_uuid))
        results.append(entry)
    return {
        "success": True,
        "kind": kind,
        "model": query_model,
        "candidates_scanned": len(rows),
        "results": results,
    }
