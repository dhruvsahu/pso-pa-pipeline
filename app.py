import json
import os
import tempfile
import uuid

from flask import (
    Flask,
    render_template,
    request,
    Response,
    stream_with_context,
    jsonify
)

from access_quality_scorer import AccessQualityScorer
from pipeline_runner import run_pipeline

# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

# In-memory session store: session_id → temp PDF path
SESSIONS = {}

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

        try:

            for step, result in run_pipeline(pdf_path, brand):

                payload = json.dumps(
                    {"step": step, "result": result},
                    default=str
                )

                yield f"data: {payload}\n\n"

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


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    app.run(
        debug=True,
        threaded=True,
        port=5000
    )
