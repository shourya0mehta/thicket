"""Build the thicket-inat-v1 dataset: plan -> embed (sharded) -> merge.

  plan   Query the iNaturalist API once and write the full list of sound
         recordings to download (targets, bird benchmark, open-set negatives).
  embed  For one shard of the plan: download audio, decode to 48 kHz mono,
         cut 3 s windows, run BirdNET v2.4 and store embeddings + logits.
  merge  Combine shard outputs into the published dataset folder.

Runs on GitHub Actions (see .github/workflows/dataset-inat.yml) because the
iNaturalist hosts are reachable there. Raw audio is never committed; only
derived features, a manifest, and per-recording attribution.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import threading  # noqa: E402

from inat_client import INatClient, RateLimiter, download, to_sound_record  # noqa: E402

PLAN_FIELDS = [
    "row",
    "group",
    "label",
    "label_common",
    "observation_id",
    "sound_id",
    "file_url",
    "license_code",
    "attribution",
    "taxon_id",
    "taxon_name",
    "common_name",
    "user_id",
    "observed_on",
    "latitude",
    "longitude",
    "obscured",
]


def cmd_plan(args: argparse.Namespace) -> None:
    cfg = json.loads(Path(args.config).read_text())
    inat = cfg["inat"]
    licenses = inat["sound_licenses"]
    lic_set = set(licenses)
    per_user = int(inat["max_per_user_per_taxon"])
    client = INatClient()
    rows: list[dict] = []
    seen_sounds: set[int] = set()
    taxa_out: dict[str, dict] = {}
    report: dict[str, dict] = {}

    def add_species(
        group: str, name: str, common: str, cap: int, place_id: int | None
    ) -> int | None:
        t = client.resolve_taxon(name, rank="species")
        if not t:
            print(f"[plan] could not resolve {name}", flush=True)
            report[name] = {"group": group, "resolved": False, "n": 0}
            return None
        taxa_out[name] = {
            "id": t["id"],
            "inat_name": t["name"],
            "common": t.get("preferred_common_name"),
        }
        per_user_count: Counter = Counter()
        n = 0
        scanned = 0
        for obs in client.sound_observations(
            t["id"], licenses, inat["quality_grade"], place_id, max_pages=6
        ):
            scanned += 1
            rec = to_sound_record(obs, lic_set)
            if rec is None or rec.sound_id in seen_sounds:
                continue
            if per_user_count[rec.user_id] >= per_user:
                continue
            per_user_count[rec.user_id] += 1
            seen_sounds.add(rec.sound_id)
            row = rec.as_row()
            row.update(group=group, label=name, label_common=common)
            rows.append(row)
            n += 1
            if n >= cap:
                break
        report[name] = {
            "group": group,
            "resolved": True,
            "taxon_id": t["id"],
            "n": n,
            "scanned": scanned,
            "users": len(per_user_count),
        }
        print(f"[plan] {group:8s} {name:32s} n={n:4d} users={len(per_user_count):4d}", flush=True)
        return int(t["id"])

    target_ids: list[int] = []
    for group in ("frogs", "insects"):
        for name, common in cfg["targets"][group]:
            tid = add_species(
                group[:-1],
                name,
                common,
                cfg["targets"]["cap_per_taxon"],
                cfg["targets"].get("place_id"),
            )
            if tid:
                target_ids.append(tid)
    for name, common in cfg["birds"]["species"]:
        add_species(
            "bird", name, common, cfg["birds"]["cap_per_taxon"], cfg["birds"].get("place_id")
        )

    neg = cfg["open_set_negatives"]
    for g in neg["groups"]:
        t = client.resolve_taxon(g["taxon"], rank=g["rank"])
        if not t:
            print(f"[plan] could not resolve group {g['taxon']}")
            continue
        per_taxon: Counter = Counter()
        per_user_count = Counter()
        n = 0
        for obs in client.sound_observations(
            t["id"],
            licenses,
            inat["quality_grade"],
            neg.get("place_id"),
            without_taxon_ids=target_ids,
            max_pages=10,
        ):
            rec = to_sound_record(obs, lic_set)
            if rec is None or rec.sound_id in seen_sounds or rec.taxon_id in target_ids:
                continue
            if (
                per_taxon[rec.taxon_id] >= neg["max_per_taxon"]
                or per_user_count[rec.user_id] >= per_user
            ):
                continue
            per_taxon[rec.taxon_id] += 1
            per_user_count[rec.user_id] += 1
            seen_sounds.add(rec.sound_id)
            row = rec.as_row()
            row.update(group=g["name"], label="", label_common="")
            rows.append(row)
            n += 1
            if n >= g["cap"]:
                break
        report[g["name"]] = {
            "group": g["name"],
            "resolved": True,
            "taxon_id": t["id"],
            "n": n,
            "distinct_taxa": len(per_taxon),
        }
        print(f"[plan] negative {g['name']:20s} n={n} taxa={len(per_taxon)}", flush=True)

    for i, r in enumerate(rows):
        r["row"] = i
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PLAN_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (out.parent / "plan_report.json").write_text(
        json.dumps({"taxa": taxa_out, "report": report, "n_rows": len(rows)}, indent=1)
    )
    print(f"[plan] wrote {len(rows)} rows to {out}")


def _ext(url: str) -> str:
    tail = url.split("?")[0].rsplit("/", 1)[-1]
    return "." + tail.rsplit(".", 1)[-1].lower() if "." in tail else ".audio"


_RATE_LOCK = threading.Lock()
_RATE: RateLimiter | None = None


def _fetch(session, row: dict, audio_dir: Path, max_bytes: int) -> tuple[dict, Path | None, int]:
    url = row["file_url"]
    if _RATE is not None and not (url.startswith("/") or url.startswith("file://")):
        with _RATE_LOCK:
            _RATE.wait()
    dest = audio_dir / f"{row['sound_id']}{_ext(url)}"
    if dest.exists() and dest.stat().st_size > 0:
        return row, dest, dest.stat().st_size
    try:
        if url.startswith("file://") or url.startswith("/"):
            src = Path(url.replace("file://", ""))
            shutil.copy(src, dest)
            return row, dest, dest.stat().st_size
        n = download(session, url, dest, max_bytes)
    except Exception:  # noqa: BLE001 - any failure marks the row as failed
        dest.unlink(missing_ok=True)
        return row, None, 0
    if n <= 0:
        dest.unlink(missing_ok=True)
        return row, None, n
    return row, dest, n


def cmd_embed(args: argparse.Namespace) -> None:
    import requests

    backend = HERE.parent.parent / "backend"
    sys.path.insert(0, str(backend))
    from thicket.models.birdnet_runtime import BirdNETRuntime, frame_windows
    from thicket.services.audio_io import AudioDecodeError, decode

    cfg = json.loads(Path(args.config).read_text())
    max_seconds = float(cfg["inat"]["max_seconds_per_recording"])
    max_bytes = int(cfg["inat"]["max_file_bytes"])
    with open(args.plan) as f:
        plan = [r for r in csv.DictReader(f) if int(r["row"]) % args.num_shards == args.shard]
    if args.limit:
        plan = plan[: args.limit]
    out = Path(args.out)
    audio_dir = Path(args.audio_dir)
    out.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    global _RATE
    if args.max_rate and args.max_rate > 0:
        _RATE = RateLimiter(1.0 / args.max_rate)
    rt = BirdNETRuntime(num_threads=args.threads)
    rt.load()
    bird_idx = np.array([i for i, lab in enumerate(rt.labels) if lab.taxon == "bird"])
    sub_names = [lab.raw for lab in rt.labels if lab.taxon != "bird"]
    sub_names += [
        rt.labels[rt.index_by_scientific[s]].raw
        for s, _ in cfg["birds"]["species"]
        if s in rt.index_by_scientific
    ]
    sub_idx = np.array(
        [next(i for i, lab in enumerate(rt.labels) if lab.raw == n) for n in sub_names]
    )

    embs, recs, starts, rms, subs, top_i, top_p, max_bird = [], [], [], [], [], [], [], []
    manifest: list[dict] = []
    session = requests.Session()
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.download_workers) as pool:
        futures = [pool.submit(_fetch, session, r, audio_dir, max_bytes) for r in plan]
        for fut in as_completed(futures):
            row, path, nbytes = fut.result()
            rec = dict(row)
            rec.update(
                status="ok", bytes=nbytes, sha256="", duration_s=0.0, n_windows=0, audio_file=""
            )
            done += 1
            if path is None:
                rec["status"] = "too_large" if nbytes < 0 else "download_failed"
                manifest.append(rec)
                continue
            rec["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            rec["audio_file"] = path.name
            try:
                x, _ = decode(path, target_sr=48000, max_seconds=max_seconds)
            except (AudioDecodeError, Exception):  # noqa: BLE001
                rec["status"] = "decode_error"
                manifest.append(rec)
                continue
            dur = len(x) / 48000
            rec["duration_s"] = round(dur, 3)
            if dur < 1.0:
                rec["status"] = "too_short"
                manifest.append(rec)
                continue
            win, st = frame_windows(x, hop_seconds=3.0, min_tail_seconds=1.0)
            logits, emb = rt.infer(win)
            probs = rt.sigmoid(logits)
            n = len(st)
            rec["n_windows"] = n
            for s in st:
                a = int(s * 48000)
                seg = x[a : a + 144000]
                rms.append(20 * np.log10(np.sqrt(np.mean(seg.astype(np.float64) ** 2)) + 1e-9))
            embs.append(emb.astype(np.float16))
            recs.append(np.full(n, int(row["sound_id"]), dtype=np.int64))
            starts.append(st.astype(np.float32))
            subs.append(logits[:, sub_idx].astype(np.float16))
            ti = np.argsort(-probs, axis=1)[:, :5]
            top_i.append(ti.astype(np.int16))
            top_p.append(np.take_along_axis(probs, ti, axis=1).astype(np.float16))
            max_bird.append(probs[:, bird_idx].max(axis=1).astype(np.float16))
            manifest.append(rec)
            if done % 50 == 0:
                el = time.time() - t0
                print(
                    f"[embed {args.shard}] {done}/{len(plan)} recs, {sum(len(e) for e in embs)} windows, {el:.0f}s",
                    flush=True,
                )

    def cat(parts, dtype, shape_tail=()):
        return np.concatenate(parts) if parts else np.zeros((0, *shape_tail), dtype=dtype)

    np.savez_compressed(
        out / f"birdnet_part_{args.shard:02d}.npz",
        embedding=cat(embs, np.float16, (1024,)),
        sound_id=cat(recs, np.int64),
        start_s=cat(starts, np.float32),
        rms_dbfs=np.asarray(rms, dtype=np.float16),
        subset_logits=cat(subs, np.float16, (len(sub_idx),)),
        subset_labels=np.asarray(sub_names),
        top5_index=cat(top_i, np.int16, (5,)),
        top5_prob=cat(top_p, np.float16, (5,)),
        max_bird_prob=cat(max_bird, np.float16),
    )
    fields = PLAN_FIELDS + ["status", "bytes", "sha256", "duration_s", "n_windows", "audio_file"]
    with open(out / f"manifest_part_{args.shard:02d}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(manifest, key=lambda r: int(r["row"])))
    stats = Counter(r["status"] for r in manifest)
    print(f"[embed {args.shard}] done in {time.time() - t0:.0f}s: {dict(stats)}", flush=True)


def cmd_merge(args: argparse.Namespace) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for d in args.inputs:
        for p in sorted(Path(d).glob("manifest_part_*.csv")):
            with open(p) as f:
                rows.extend(csv.DictReader(f))
        for p in sorted(Path(d).glob("*_part_*.npz")):
            shutil.copy(p, out / p.name)
    rows.sort(key=lambda r: int(r["row"]))
    fields = list(rows[0].keys()) if rows else PLAN_FIELDS
    fields = [f for f in fields if f != "audio_file"]
    with open(out / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(out / "ATTRIBUTION.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sound_id", "observation_url", "license", "attribution"])
        for r in rows:
            if r.get("status") == "ok":
                w.writerow(
                    [
                        r["sound_id"],
                        f"https://www.inaturalist.org/observations/{r['observation_id']}",
                        r["license_code"],
                        r["attribution"],
                    ]
                )
    by_group: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_group[r["group"]][r["status"]] += 1
    summary = {g: dict(c) for g, c in by_group.items()}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--config", required=True)
    p.add_argument("--out", required=True)
    e = sub.add_parser("embed")
    e.add_argument("--config", required=True)
    e.add_argument("--plan", required=True)
    e.add_argument("--shard", type=int, default=0)
    e.add_argument("--num-shards", type=int, default=1)
    e.add_argument("--out", required=True)
    e.add_argument("--audio-dir", required=True)
    e.add_argument("--threads", type=int, default=None)
    e.add_argument("--download-workers", type=int, default=3)
    e.add_argument("--limit", type=int, default=0)
    e.add_argument(
        "--max-rate", type=float, default=0.5, help="max downloads per second for this shard"
    )
    m = sub.add_parser("merge")
    m.add_argument("--inputs", nargs="+", required=True)
    m.add_argument("--out", required=True)
    args = ap.parse_args()
    {"plan": cmd_plan, "embed": cmd_embed, "merge": cmd_merge}[args.cmd](args)


if __name__ == "__main__":
    main()
