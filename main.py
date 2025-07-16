from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

MAP_OFFSETS = {
    "fuel": 0x1D8710,
    "torque_limiter": 0x1DA000,
    "drivers_wish": 0x1DB000,
    "fuel_quantity": 0x1DC000,
    "injection_timing": 0x1DD000,
    "boost_pressure": 0x1DE000,
    "rail_pressure": 0x1DF000,
    "turbo_duty": 0x1E0000,
    "smoke_limiter": 0x1E1000,
    "iat_ect_correction": 0x1E2000,  # <-- comma ที่นี่
    "egr": 0x1E3000,
    "throttle": 0x1E4000,
    "dtc_off": 0x1F0000,
}


@app.route("/analyze", methods=["POST"])
def analyze_bin():
    bin_file = request.files.get('bin')
    map_type = (request.form.get('type') or 'fuel').lower()

    if not bin_file:
        app.logger.error("Missing file 'bin'")
        return jsonify({ "error": "Missing file 'bin'" }), 400

    if map_type not in MAP_OFFSETS:
        app.logger.error(f"Unsupported map type: {map_type}")
        return jsonify({ "error": f"Unsupported map type '{map_type}'" }), 400

    content = bin_file.read()
    offset = MAP_OFFSETS[map_type]
    if len(content) < offset + 256:
        app.logger.error("File too small for expected offset")
        return jsonify({ "error": "File too small for expected offset" }), 400

    block = content[offset : offset + 256]
    map_2d = [[round(b * 0.05, 2) for b in block[i*16:(i+1)*16]] for i in range(16)]

    return jsonify({
        "type": map_type.capitalize(),
        "offset": hex(offset),
        "map": map_2d
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
