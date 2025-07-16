from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

# ตำแหน่ง offset ของ Map block + แกน X/Y
MAP_OFFSETS = {
    "fuel": {
        "block": 0x1D8710,
        "x_axis": 0x1D8610,
        "y_axis": 0x1D8600
    },
    "torque_limiter": {
        "block": 0x1DA000,
        "x_axis": 0x1D9F10,
        "y_axis": 0x1D9F00
    },
    "drivers_wish": {
        "block": 0x1DB000,
        "x_axis": 0x1DAF10,
        "y_axis": 0x1DAF00
    },
    "fuel_quantity": {
        "block": 0x1DC000,
        "x_axis": 0x1DBF10,
        "y_axis": 0x1DBF00
    },
    "injection_timing": {
        "block": 0x1DD000,
        "x_axis": 0x1DCF10,
        "y_axis": 0x1DCF00
    },
    "boost_pressure": {
        "block": 0x1DE000,
        "x_axis": 0x1DDF10,
        "y_axis": 0x1DDF00
    },
    "rail_pressure": {
        "block": 0x1DF000,
        "x_axis": 0x1DEF10,
        "y_axis": 0x1DEF00
    },
    "turbo_duty": {
        "block": 0x1E0000,
        "x_axis": 0x1DFF10,
        "y_axis": 0x1DFF00
    },
    "smoke_limiter": {
        "block": 0x1E1000,
        "x_axis": 0x1E0F10,
        "y_axis": 0x1E0F00
    },
    "iat_ect_correction": {
        "block": 0x1E2000,
        "x_axis": 0x1E1F10,
        "y_axis": 0x1E1F00
    },
    "egr": {
        "block": 0x1E3000,
        "x_axis": 0x1E2F10,
        "y_axis": 0x1E2F00
    },
    "throttle": {
        "block": 0x1E4000,
        "x_axis": 0x1E3F10,
        "y_axis": 0x1E3F00
    },
    "dtc_off": {
        "block": 0x1F0000,
        "x_axis": 0x1EFF10,
        "y_axis": 0x1EFF00
    }
}

def parse_axis(raw_bytes, scale):
    return [round(b * scale) for b in raw_bytes]

@app.route("/analyze", methods=["POST"])
def analyze_bin():
    bin_file = request.files.get('bin')
    map_type = (request.form.get('type') or 'fuel').lower()

    if not bin_file or map_type not in MAP_OFFSETS:
        return jsonify({ "error": "Missing file or unsupported map type" }), 400

    content = bin_file.read()
    offsets = MAP_OFFSETS[map_type]

    try:
        if len(content) < offsets["block"] + 256:
            return jsonify({ "error": "File too small for expected offset" }), 400

        # อ่านแกน X/Y: 16 bytes ต่อแกน
        x_raw = content[offsets["x_axis"] : offsets["x_axis"] + 16]
        y_raw = content[offsets["y_axis"] : offsets["y_axis"] + 16]

        x_axis = parse_axis(x_raw, scale=1.0)     # เช่น % LOAD
        y_axis = parse_axis(y_raw, scale=20.0)    # เช่น RPM

        # อ่าน map block 256 bytes → 16×16
        block = content[offsets["block"] : offsets["block"] + 256]
        map_2d = [[round(b * 0.05, 2) for b in block[i*16:(i+1)*16]] for i in range(16)]

        return jsonify({
            "type": map_type.capitalize(),
            "offset": hex(offsets["block"]),
            "x_axis": x_axis,
            "y_axis": y_axis,
            "map": map_2d
        })
    
    except Exception as e:
        app.logger.error(f"Processing error: {str(e)}")
        return jsonify({ "error": "Processing error" }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
