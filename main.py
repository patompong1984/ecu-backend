from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os
import struct
from werkzeug.middleware.proxy_fix import ProxyFix

# สร้าง Flask App
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# --- Conversion Settings สำหรับ D-MAX 1.9 Ddi ---
MAP_CONVERSION_SETTINGS = {
    "fuel": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "torque_limiter": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "drivers_wish": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "fuel_quantity": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "injection_timing": {"data_type": "8bit", "factor": 0.235, "offset": -20.0, "x_scale": 1.0, "y_scale": 20.0},
    "boost_pressure": {"data_type": "8bit", "factor": 15.686, "offset": -1000, "x_scale": 1.0, "y_scale": 20.0},
    "rail_pressure": {"data_type": "16bit", "factor": 0.02749, "offset": 0, "endian": "<H", "x_scale": 1.0, "y_scale": 20.0},
    "turbo_duty": {"data_type": "8bit", "factor": 0.392, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "smoke_limiter": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "iat_ect_correction": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "egr": {"data_type": "8bit", "factor": 0.392, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "throttle": {"data_type": "8bit", "factor": 0.392, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "dtc_off": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 1.0}
}

# --- Offset ของแต่ละ Map ---
MAP_OFFSETS = {
    "fuel": {"block": 0x1D8710, "x_axis": 0x1D8610, "y_axis": 0x1D8600},
    "torque_limiter": {"block": 0x1DA000, "x_axis": 0x1D9F10, "y_axis": 0x1D9F00},
    "drivers_wish": {"block": 0x1DB000, "x_axis": 0x1DAF10, "y_axis": 0x1DAF00},
    "fuel_quantity": {"block": 0x1DC000, "x_axis": 0x1DBF10, "y_axis": 0x1DBF00},
    "injection_timing": {"block": 0x1DD000, "x_axis": 0x1DCF10, "y_axis": 0x1DCF00},
    "boost_pressure": {"block": 0x1DE000, "x_axis": 0x1DDF10, "y_axis": 0x1DDF00},
    "rail_pressure": {"block": 0x1DF000, "x_axis": 0x1DEF10, "y_axis": 0x1DEF00},
    "turbo_duty": {"block": 0x1E0000, "x_axis": 0x1DFF10, "y_axis": 0x1DFF00},
    "smoke_limiter": {"block": 0x1E1000, "x_axis": 0x1E0F10, "y_axis": 0x1E0F00},
    "iat_ect_correction": {"block": 0x1E2000, "x_axis": 0x1E1F10, "y_axis": 0x1E1F00},
    "egr": {"block": 0x1E3000, "x_axis": 0x1E2F10, "y_axis": 0x1E2F00},
    "throttle": {"block": 0x1E4000, "x_axis": 0x1E3F10, "y_axis": 0x1E3F00},
    "dtc_off": {"block": 0x1F0000, "x_axis": 0x1EFF10, "y_axis": 0x1EFF00}
}

# ฟังก์ชันแปลงแกน
def parse_axis(raw_bytes, scale):
    return [round(b * scale) for b in raw_bytes]

# Health Check
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "ECU Map Analyzer"}), 200

# Error Handlers
@app.errorhandler(400)
def bad_request(e): return jsonify({"error": "Bad request"}), 400

@app.errorhandler(404)
def not_found(e): return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(413)
def request_too_large(e): return jsonify({"error": "File too large. Max size 4MB"}), 413

@app.errorhandler(500)
def internal_error(e): return jsonify({"error": "Internal server error"}), 500

# Endpoint วิเคราะห์ไฟล์ .bin
@app.route("/analyze", methods=["POST"])
def analyze_bin():
    if 'bin' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    bin_file = request.files['bin']
    map_type = (request.form.get('type') or 'fuel').lower()
    if map_type not in MAP_OFFSETS:
        return jsonify({"error": f"Unsupported map type: {map_type}"}), 400

    try:
        content = bin_file.read()
        offsets = MAP_OFFSETS[map_type]
        conv = MAP_CONVERSION_SETTINGS.get(map_type)

        data_type = conv["data_type"]
        value_size = 2 if data_type == "16bit" else 1
        map_byte_size = 16 * 16 * value_size
        required_size = max(offsets["block"] + map_byte_size,
                            offsets["x_axis"] + 16,
                            offsets["y_axis"] + 16)

        if len(content) < required_size:
            return jsonify({"error": "File too small for this map"}), 400

        x_axis = parse_axis(content[offsets["x_axis"]:offsets["x_axis"] + 16], conv["x_scale"])
        y_axis = parse_axis(content[offsets["y_axis"]:offsets["y_axis"] + 16], conv["y_scale"])
        block_raw = content[offsets["block"]:offsets["block"] + map_byte_size]

        factor = conv["factor"]
        offset = conv["offset"]
        endian = conv.get("endian", None)

        map_2d = []
        for i in range(16):
            row = []
            for j in range(16):
                if data_type == "8bit":
                    raw = block_raw[i * 16 + j]
                elif data_type == "16bit":
                    idx = (i * 16 + j) * 2
                    value_bytes = block_raw[idx:idx + 2]
                    raw = struct.unpack(endian, value_bytes)[0] if len(value_bytes) == 2 else 0
                else:
                    raw = 0
                row.append(round(raw * factor + offset, 2))
            map_2d.append(row)

        return jsonify({
            "type": map_type,
            "offset": hex(offsets["block"]),
            "x_axis": x_axis,
            "y_axis": y_axis,
            "map": map_2d
        })

    except Exception as e:
        app.logger.exception(f"Error analyzing {map_type}")
        return jsonify({"error": str(e)}), 500

# เริ่ม Flask Server
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    if not debug_mode:
        try:
            from waitress import serve
            serve(app, host="0.0.0.0", port=port)
        except ImportError:
            app.run(host="0.0.0.0", port=port, debug=False)
    else:
        app.run(host="0.0.0.0", port=port, debug=True)
