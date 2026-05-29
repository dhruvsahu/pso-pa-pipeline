import json
import os
import tempfile
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
from result_formatter import flatten_result

# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

# In-memory session store: session_id → temp PDF path
SESSIONS = {}

# Output CSV path written after every UI analysis
RESULTS_CSV = "outputs/results.csv"

CSV_COLUMNS = [
    "Filename", "Brand", "Age",
    "Step Therapy Requirements Documented in Policy",
    "Number of Steps through Brands", "Number of Steps through Generic",
    "Step through Phototherapy", "TB Test required", "Specialist Types",
    "Quantity Limits", "Initial Authorization Duration(in-months)",
    "Reauthorization Duration(in-months)", "Reauthorization Required",
    "Reauthorization Requirements Documented in Policy", "Access Score",
]


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
    SESSIONS[session_id] = tmp.name

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

    pdf_path = SESSIONS.get(session_id)

    if not pdf_path or not os.path.exists(pdf_path):
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

            # Clean up temp file and session
            try:
                os.unlink(pdf_path)
            except OSError:
                pass

            SESSIONS.pop(session_id, None)

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
