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


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    app.run(
        debug=True,
        threaded=True,
        port=5000
    )
