from flask import jsonify
from flask_limiter import Limiter


def attach_global_limiter(
    app,
    storage_uri: str,
    main_limit_per_minute: int,
    autocomplete_limit_per_minute: int,
):
    limiter = Limiter(
        app=app,
        key_func=lambda: "global",  # all IPs share the same bucket
        storage_uri=storage_uri,
        default_limits=[],
    )
    main_limit = limiter.shared_limit(
        f"{main_limit_per_minute}/minute;{main_limit_per_minute*2}/10 minutes", scope="global-main"
    )
    autocomplete_limit = limiter.shared_limit(
        f"{autocomplete_limit_per_minute}/minute;{autocomplete_limit_per_minute*2}/10 minutes", scope="global-autocomplete"
    )

    @app.errorhandler(429)
    def handle_rate_limit(_):
        return jsonify({"error": "Rate limit exceeded."}), 429

    return main_limit, autocomplete_limit
