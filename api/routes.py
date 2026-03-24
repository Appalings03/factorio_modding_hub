# api/routes.py

# Le mode est stocké en session ou passé en query param
# Les deux modes partagent le MÊME backend — seuls les templates changent

@app.route("/search")
def search():
    mode = request.args.get("mode", session.get("mode", "beginner"))
    results = search_engine.query(
        q=request.args.get("q"),
        filters=request.args.get("filters"),
        mode=mode
    )
    template = "search_beginner.html" if mode == "beginner" else "search_expert.html"
    return render_template(template, results=results)