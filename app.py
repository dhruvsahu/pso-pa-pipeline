import json
import os
import tempfile
import uuid
import time
import threading

import csv

from flask import (
    Flask,
    render_template,
    request,
    Response,
    stream_with_context,
    jsonify,
    send_file,
)

from collections import Counter
from statistics import median

from access_quality_scorer import AccessQualityScorer
from pipeline_runner import run_pipeline
from result_formatter import flatten_result, SUBMISSION_COLUMNS

# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

# In-memory session store: session_id → (temp PDF path, created_at).
# Guarded by a lock because Flask runs with threaded=True. Entries older
# than SESSION_TTL_SECONDS are swept on each upload, so an abandoned upload
# (client never opens /stream) cannot leak its temp file or dict entry.
SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()
SESSION_TTL_SECONDS = 600


def _sweep_sessions():
    """Pop and delete temp files for sessions older than the TTL."""
    now = time.time()
    with _SESSIONS_LOCK:
        expired = [
            sid for sid, entry in SESSIONS.items()
            if now - entry[1] > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            entry = SESSIONS.pop(sid)
            path = entry[0]
            try:
                os.unlink(path)
            except OSError:
                pass


def _register_session(path, original_name="uploaded_pdf"):
    """Store a temp PDF path under a new session id and return the id."""
    sid = str(uuid.uuid4())
    with _SESSIONS_LOCK:
        SESSIONS[sid] = (path, time.time(), original_name)
    return sid


def _get_session(sid):
    """Return (temp_path, original_name) for a session, or (None, None)."""
    with _SESSIONS_LOCK:
        entry = SESSIONS.get(sid)
    if entry:
        return entry[0], entry[2]
    return None, None


def _discard_session(sid):
    """Pop a session and unlink its temp file (idempotent, lock-guarded)."""
    with _SESSIONS_LOCK:
        entry = SESSIONS.pop(sid, None)
    if entry:
        try:
            os.unlink(entry[0])
        except OSError:
            pass


# Output CSV path written after every UI analysis
RESULTS_CSV = "outputs/results.csv"

# Column schema is owned by result_formatter (single source of truth)
# so the UI output and the batch output cannot drift apart.


def append_to_csv(result_dict):
    """Append one flattened result row to outputs/results.csv."""
    os.makedirs("outputs", exist_ok=True)
    write_header = not os.path.exists(RESULTS_CSV)
    row = flatten_result(result_dict)
    with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUBMISSION_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

# Brand list (for dropdown) — loaded once at startup
_scorer = AccessQualityScorer()
BRANDS = sorted(_scorer.fda_baselines.keys())


# =========================================================
# ROUTES
# =========================================================

@app.route("/")
def index():
    return render_template("index.html", brands=BRANDS)


@app.route("/upload", methods=["POST"])
def upload():
    """
    Accepts a multipart PDF upload, saves to a temp file,
    returns a session_id the client uses to open the SSE
    stream.
    """

    pdf = request.files.get("pdf")

    if not pdf:
        return jsonify({"error": "No PDF uploaded"}), 400

    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".pdf"
    )
    pdf.save(tmp.name)
    tmp.close()

    original_name = pdf.filename or "uploaded_pdf"

    # Opportunistically reap abandoned uploads before adding a new one.
    _sweep_sessions()

    session_id = _register_session(tmp.name, original_name)

    return jsonify({"session_id": session_id})


@app.route("/stream")
def stream():
    """
    SSE endpoint.  Iterates pipeline_runner.run_pipeline()
    and yields each result as a text/event-stream event.
    Cleans up the temp file when the stream closes.
    """

    session_id = request.args.get("session_id", "")
    brand = request.args.get("brand", "")

    pdf_path, original_name = _get_session(session_id)

    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "Session not found"}), 404

    def generate():

        # Accumulate step results to build the combined record
        collected = {"brand": brand, "filename": original_name}

        try:

            for step, result in run_pipeline(pdf_path, brand):

                payload = json.dumps(
                    {"step": step, "result": result},
                    default=str
                )

                yield f"data: {payload}\n\n"

                # Map pipeline step names to result keys
                key_map = {
                    "age":            "age",
                    "step_therapy":   "step_therapy",
                    "authorization":  "authorization",
                    "utilization":    "utilization_management",
                    "clinical_access":"clinical_access",
                    "score":          "access_quality",
                }
                if step in key_map:
                    collected[key_map[step]] = result

            # All steps done — save row to CSV
            try:
                append_to_csv(collected)
            except Exception as csv_err:
                print(f"[CSV SAVE ERROR] {csv_err}")

        except Exception as e:

            error_payload = json.dumps(
                {"step": "error", "message": str(e)}
            )
            yield f"data: {error_payload}\n\n"

        finally:

            # Clean up temp file and session (lock-guarded, idempotent)
            _discard_session(session_id)

        yield 'data: {"step": "done"}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@app.route("/download/results")
def download_results():
    """Serve outputs/results.csv as a file download."""
    if not os.path.exists(RESULTS_CSV):
        return jsonify({"error": "No results yet — run an analysis first."}), 404
    return send_file(
        os.path.abspath(RESULTS_CSV),
        mimetype="text/csv",
        as_attachment=True,
        download_name="results.csv",
    )


@app.route("/download/batch-results")
def download_batch_results():
    """Serve outputs/final_access_results.csv as a file download."""
    path = "outputs/final_access_results.csv"
    if not os.path.exists(path):
        return jsonify({"error": "No batch results yet — run the pipeline first."}), 404
    return send_file(
        os.path.abspath(path),
        mimetype="text/csv",
        as_attachment=True,
        download_name="final_access_results.csv",
    )


# =========================================================
# DASHBOARD
# =========================================================

BATCH_JSON = "outputs/final_access_results.json"


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/dashboard-data")
def dashboard_data():
    """
    Compute summary statistics from the batch JSON and return as
    a single JSON payload consumed by the dashboard charts.
    """
    if not os.path.exists(BATCH_JSON):
        return jsonify({}), 200

    with open(BATCH_JSON, "r", encoding="utf-8") as f:
        results = json.load(f)

    if not results:
        return jsonify({}), 200

    # ------ scores + categories ------
    scores = []
    categories = []
    alignments = []
    entries = []  # (filename, brand, score, category)

    # ------ restriction counters ------
    brand_step_counts = []
    generic_step_counts = []
    n_brand_steps = 0
    n_generic_steps = 0
    n_phototherapy = 0
    n_tb = 0
    n_specialist = 0
    n_ql = 0
    n_reauth = 0

    # ------ per-brand accumulators ------
    brand_scores = {}  # brand -> [scores]

    for r in results:
        aq = r.get("access_quality", {})
        score = aq.get("access_quality_score")
        if score is None:
            continue

        cat = aq.get("access_category", "Unknown")
        align = aq.get("fda_alignment", "Unknown")
        brand = r.get("brand", "?")
        fname = r.get("filename", "?")

        scores.append(score)
        categories.append(cat)
        alignments.append(align)
        entries.append({
            "filename": fname,
            "brand": brand,
            "score": score,
            "category": cat,
        })

        # Per-brand
        brand_scores.setdefault(brand, []).append(score)

        # Step therapy
        st = r.get("step_therapy", {})
        bs = st.get("brand_steps")
        gs = st.get("generic_steps")
        photo = st.get("phototherapy_required")

        if bs is not None and str(bs).upper() != "NA":
            brand_step_counts.append(int(bs))
            if int(bs) > 0:
                n_brand_steps += 1
        else:
            brand_step_counts.append("NA")

        if gs is not None and str(gs).upper() != "NA":
            generic_step_counts.append(int(gs))
            if int(gs) > 0:
                n_generic_steps += 1
        else:
            generic_step_counts.append("NA")

        if str(photo).strip().lower() == "yes":
            n_phototherapy += 1

        # Clinical access
        ca = r.get("clinical_access", {})
        if str(ca.get("tb_test_required", "")).strip().lower() == "yes":
            n_tb += 1
        spec = ca.get("specialist_types", [])
        if isinstance(spec, list) and len(spec) > 0:
            n_specialist += 1
        elif isinstance(spec, str) and spec.upper() not in ("NA", ""):
            n_specialist += 1

        # Utilization
        um = r.get("utilization_management", {})
        ql = um.get("quantity_limits")
        if isinstance(ql, list) and len(ql) > 0:
            n_ql += 1
        elif isinstance(ql, str) and ql.upper() not in ("NA", "", "NO"):
            n_ql += 1

        # Reauth
        auth = r.get("authorization", {})
        reauth = str(auth.get("reauthorization_required", "")).strip().lower()
        reauth_dur = auth.get("reauthorization_duration_months")
        reauth_reqs = auth.get("reauthorization_requirements", [])
        has_reauth = (
            reauth == "yes"
            or (reauth_dur is not None and str(reauth_dur).upper() not in ("NA", ""))
            or (isinstance(reauth_reqs, list) and len(reauth_reqs) > 0)
        )
        if has_reauth:
            n_reauth += 1

    total = len(scores)
    if total == 0:
        return jsonify({}), 200

    # ------ brand stats ------
    brand_stats = {}
    for b, sc_list in brand_scores.items():
        brand_stats[b] = {
            "avg": round(sum(sc_list) / len(sc_list), 1),
            "count": len(sc_list),
            "min": min(sc_list),
            "max": max(sc_list),
        }

    # ------ step distribution ------
    # Keys are strings throughout ("0","1","2","3","NA") so JSON
    # serialization never compares str vs int during key sorting.
    def count_steps(lst):
        out = {}
        for v in lst:
            key = str(v)
            out[key] = out.get(key, 0) + 1
        return out

    # ------ sort entries for tables ------
    sorted_entries = sorted(entries, key=lambda e: e["score"], reverse=True)

    payload = {
        "total": total,
        "avg_score": round(sum(scores) / total, 1),
        "median_score": median(scores),
        "min_score": min(scores),
        "max_score": max(scores),
        "scores": scores,
        "categories": dict(Counter(categories)),
        "fda_alignment": dict(Counter(alignments)),
        "brand_stats": brand_stats,
        "restrictions": {
            "brand_steps": n_brand_steps,
            "generic_steps": n_generic_steps,
            "phototherapy": n_phototherapy,
            "tb_test": n_tb,
            "specialist": n_specialist,
            "quantity_limits": n_ql,
            "reauth": n_reauth,
        },
        "step_distribution": {
            "brand": count_steps(brand_step_counts),
            "generic": count_steps(generic_step_counts),
        },
        "top_policies": sorted_entries[:10],
        "bottom_policies": sorted_entries[-10:][::-1],
    }

    return jsonify(payload)


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    app.run(
        debug=True,
        threaded=True,
        port=5000
    )
