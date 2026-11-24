"""Connect lighting-test intake, previews, source probing and retained results."""

from io import BytesIO
from pathlib import Path

from flask import Blueprint, Response, jsonify, render_template, request, send_file

from image_lab.validation import Invalid

from . import alignment, analysis, demo, frame, model, output
from .store import Library


def payload():
    return model.document(request.get_json(silent=True))


def install(app, root):
    library = Library(root)
    desk = Blueprint("beam", __name__, url_prefix="/beam")

    @app.get("/")
    def home():
        return render_template("beambench.html", modes=model.MODES)

    @desk.get("/health")
    def health():
        return jsonify(status="ready", service="beambench")

    @desk.get("/panels")
    def panels():
        return jsonify(library.list())

    @desk.post("/demo")
    def practice():
        return jsonify(demo.create(library)), 201

    @desk.post("/panels")
    def upload():
        inputs = {}
        for role in ("a", "b"):
            upload_input = request.files.get(role)
            if upload_input and upload_input.filename:
                filename = model.text(Path(upload_input.filename).name, maximum=255)
                image = frame.decode(upload_input.stream.read(model.MAX_UPLOAD + 1))
                inputs[role] = image, filename
        if "a" not in inputs:
            raise Invalid("Add a main lighting photo.")
        size = inputs["a"][0].size
        if any(image.size != size for image, _ in inputs.values()):
            raise Invalid("The reference photo must have the same size and framing as the main photo.")
        title = model.text(request.form.get("title"), Path(inputs["a"][1]).stem)
        return jsonify(library.create(title, inputs, model.defaults(*size))), 201

    @desk.get("/panels/<panel_id>")
    def panel(panel_id):
        return jsonify(library.panel(panel_id))

    @desk.get("/panels/<panel_id>/source/<role>.png")
    def source(panel_id, role):
        archive = request.args.get("report")
        record = library.report(panel_id, archive) if archive else library.panel(panel_id)
        return send_file(library.source(record, role), mimetype="image/png",
                         as_attachment="download" in request.args, download_name=f"lighting-{role}.png", max_age=0)

    @desk.post("/panels/<panel_id>/prepared")
    def preparation(panel_id):
        chosen = payload()
        project = model.text(chosen.get("project"))
        result_id = model.text(chosen.get("result"))
        preparation = app.extensions["results"]
        meta = preparation.metadata(project, result_id)
        if meta["stale"]:
            raise Invalid("Run the preparation again before attaching its result.")
        record = library.panel(panel_id)
        if (meta["width"], meta["height"]) != (record["width"], record["height"]):
            raise Invalid("The prepared reference must retain the main photo dimensions.")
        path = preparation.image_path(project, "image", result_id)
        photo = frame.decode(path.read_bytes())
        provenance = {"project": project, "result": result_id}
        return jsonify(library.set_companion(panel_id, chosen.get("revision"), photo, "Prepared reference.png", provenance))

    @desk.put("/panels/<panel_id>/settings")
    def revise(panel_id):
        data = payload()
        record = library.panel(panel_id)
        settings = model.settings(record, data.get("settings", {}))
        return jsonify(library.revise(panel_id, data.get("revision"), settings))

    def measurement(record, data):
        settings = model.settings(record, data.get("settings", {}))
        mode = model.mode(data.get("mode"))
        return {**analysis.inspect(library, record, mode, settings), "settings": settings, "source": settings["source"]}

    @desk.post("/panels/<panel_id>/preview")
    def preview(panel_id):
        record = library.panel(panel_id)
        return jsonify(measurement(record, payload()))

    @desk.post("/panels/<panel_id>/alignment")
    def align(panel_id):
        record = library.panel(panel_id)
        if "b" not in record["sources"]:
            raise Invalid("Add a second aligned photo to compare lighting.")
        settings = model.settings(record, payload().get("settings", {}))
        main = frame.pixels(library, record, "a")
        reference = frame.pixels(library, record, "b")
        return jsonify(alignment.suggest(main, reference, settings["box"]))

    @desk.post("/panels/<panel_id>/point")
    def sample(panel_id):
        data = payload()
        saved_id = data.get("report")
        record = library.report(panel_id, saved_id) if saved_id else library.panel(panel_id)
        current = record["settings"] if saved_id else model.settings(record, data.get("settings", {}))
        role = current["source"]
        x, y = model.point(data.get("point"), record["width"], record["height"])
        rgb = frame.pixels(library, record, role)[y, x]
        answer = {"x": x, "y": y, "rgb": rgb.tolist(), "luma": round(float(frame.luma(rgb)), 3),
                  "source": role}
        other = "b" if role == "a" else "a"
        mode = record.get("mode") if saved_id else data.get("mode")
        if mode == "compare" and other in record["sources"]:
            shift = current.get("shift_x", 0) if role == "a" else -current.get("shift_x", 0)
            cx = x + shift
            if 0 <= cx < record["width"]:
                rgb = frame.pixels(library, record, other)[y, cx]
                answer["counterpart"] = {"x": cx, "y": y, "rgb": rgb.tolist(),
                                         "luma": round(float(frame.luma(rgb)), 3), "source": other}
            else:
                answer["counterpart"] = None
        return jsonify(answer)

    @desk.post("/panels/<panel_id>/reports")
    def retain(panel_id):
        data = payload()
        record = library.panel(panel_id)
        result = measurement(record, data)
        latest, saved = library.retain(panel_id, data.get("revision"), result)
        return jsonify(panel=latest, report=saved), 201

    @desk.get("/panels/<panel_id>/reports/<report_id>")
    def report(panel_id, report_id):
        return jsonify(library.report(panel_id, report_id))

    @desk.get("/panels/<panel_id>/reports/<report_id>/report.csv")
    def csv(panel_id, report_id):
        saved = library.report(panel_id, report_id)
        return Response(output.table(saved), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=lighting-{report_id[:8]}.csv"})

    @desk.get("/panels/<panel_id>/reports/<report_id>/overlay.png")
    def marked(panel_id, report_id):
        saved = library.report(panel_id, report_id)
        marked_photo = output.overlay(library.source(saved, saved["source"]), saved)
        return send_file(BytesIO(marked_photo), mimetype="image/png", as_attachment=True,
                         download_name=f"lighting-{report_id[:8]}-marked.png", max_age=0)

    app.register_blueprint(desk)
