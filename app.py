import json
import os
import tempfile
import threading
import time
import uuid

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

# In-memory session store: session_id → (temp_path, created_at)
# All reads/writes are protected by SESSIONS_LOCK.
SESSIONS: dict = {}
SESSIONS_LOCK = threading.Lock()

# Sessions older than this many seconds are swept on the next /upload
SESSION_TTL_SECONDS = 600  # 10 minutes

# Output CSV path written after every UI analysis
RESULTS_CSV = "outputs/results.csv"

# Column schema imported from result_formatter — single source of truth
CSV_COLUMNS = SUBMISSION_COLUMNS


def _sweep_expired_sessions():
    """Remove sessions older than SESSION_TTL_SECONDS and unlink their temp files."""
    cutoff = time.time() - SESSION_TTL_SECONDS
    with SESSIONS_LOCK:
        expired = [
            sid for sid, (path, created_at) in SESSIONS.items()
            if created_at < cutoff
        ]
        for sid in expired:
            path, _ = SESSIONS.pop(sid)
            try:
                os.unlink(path)
            except OSError:
                pass


def append_to_csv(result_dict):
    """Append one flattened result row to outputs/results.csv."""
    os.makedirs("outputs", exist_ok=True)
    write_header = not os.path.exists(RESULTS_CSV)
    row = flatten_result(result_dict)
    with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
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

    # Sweep stale sessions before accepting the new upload
    _sweep_expired_sessions()

    pdf = request.files.get("pdf")

    if not pdf:
        return jsonify({"error": "No PDF uploaded"}), 400

    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".pdf"
    )
    pdf.save(tmp.name)
    tmp.close()

    session_id = str(uuid.uuid4())
    with SESSIONS_LOCK:
        SESSIONS[session_id] = (tmp.name, time.time())

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

    with SESSIONS_LOCK:
        session_entry = SESSIONS.get(session_id)

    if not session_entry:
        return jsonify({"error": "Session not found"}), 404

    pdf_path, _ = session_entry

    if not os.path.exists(pdf_path):
        return jsonify({"error": "Session not found"}), 404

    def generate():

        # Accumulate step results to build the combined record
        collected = {"brand": brand, "filename": "uploaded_pdf"}

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

            # Clean up temp file and session under lock
            with SESSIONS_LOCK:
                SESSIONS.pop(session_id, None)
            try:
                os.unlink(pdf_path)
            except OSError:
                pass

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
