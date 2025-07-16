from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import struct
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ✅ ข้อมูลแมพจาก WinOLS
MAP_OFFSETS = {
    "limit_iq_1": {"block": 0x141918, "size": (26, 21)},
    "limit_iq_2": {"block": 0x141D5C, "size": (26, 21)},
    "limit_iq_3": {"block": 0x1421A0, "size": (26, 21)},
    "torque_tps_1": {"block": 0x143FA6, "size": (26, 21)},
    "egr_target": {"block": 0x148E36, "size": (21, 11)},
    "pump_command": {"block": 0x14DD54, "size": (21, 15)},
    "injector_1": {"block": 0x161560, "size": (14, 25)},
    "injector_2": {"block": 0x161840, "size": (14, 25)},
    "torque_tps_2": {"block": 0x1633A0, "size": (26, 21)},
    "torque_tps_3": {"block": 0x16571A, "size": (26, 21)},
    "limit_baro_1": {"block": 0x166176, "size": (23, 10)},
    "limit_baro_2": {"block": 0x16635A, "size": (23, 5)},
    "limit_baro_3": {"block": 0x160526, "size": (23, 5)},
    "limit_torque": {"block": 0x167002, "size": (23, 10)},
    "torque_gear": {"block": 0x1681A, "size": (25, 6)},
    "limit_crp": {"block": 0x1957C2, "size": (26, 20)},
    "green_1": {"block": 0x1958C0, "size": (26, 20)},
    "green_2": {"block": 0x195915, "size": (26, 20)},
    "green_3": {"block": 0x195A56, "size": (26, 20)},
    "green_4": {"block": 0x1970E, "size": (21, 20)},
    "green_5": {"block": 0x197475, "size": (25, 20)},
    "turbo": {"block": 0x19541C, "size": (21, 14)},
    "turbo_meter": {"block": 0x195E62, "size": (21, 9)},
    "dtc_off": {"block": 0x1D0018, "size": (5, 25)}
}

# ✅ รูปแบบการอ่าน map ที่รองรับ
MAP_CONVERSION_SETTINGS = {
    "default_8bit": {"data_type": "8bit", "factor": 1.0, "offset": 0},
    "default_16bit": {"data_type": "16bit", "factor": 0.02749, "offset": 0, "endian": "<H"}
}

def parse_axis(length, scale):
    return [round(i * scale, 2) for i in range(length)]

@app.route("/analyze", methods=["POST"])
def analyze_dynamic_map():
    if 'bin' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    map_type = request.form.get("type")
    if map_type not in MAP_OFFSETS:
        return jsonify({"error": f"Unknown map type: {map_type}"}), 400

    conv_key = request.form.get("format") or "default_8bit"
    conv = MAP_CONVERSION_SETTINGS.get(conv_key)
    if not conv:
        return jsonify({"error": f"Unknown conversion format: {conv_key}"}), 400

    block_offset = MAP_OFFSETS[map_type]["block"]
    rows, cols = MAP_OFFSETS[map_type]["size"]
    total_bytes = rows * cols * (2 if conv["data_type"] == "16bit" else 1)

    bin_file = request.files["bin"]
    content = bin_file.read()

    if len(content) < block_offset + total_bytes:
        return jsonify({"error": "File too small for this map"}), 400

    raw_block = content[block_offset:block_offset + total_bytes]
    factor = conv["factor"]
    offset_val = conv["offset"]
    endian = conv.get("endian")

    map_data = []
    for i in range(rows):
        row = []
        for j in range(cols):
            try:
                if conv["data_type"] == "8bit":
                    raw = raw_block[i * cols + j]
                else:
                    idx = (i * cols + j) * 2
                    raw = struct.unpack(endian, raw_block[idx:idx + 2])[0]
                value = round(raw * factor + offset_val, 2)
                row.append(value)
            except:
                row.append(None)
        map_data.append(row)

    return jsonify({
        "type": map_type,
        "unit": "?",  # เสริมได้ภายหลัง
        "offset": hex(block_offset),
        "x_axis": parse_axis(cols, 1.0),
        "y_axis": parse_axis(rows, 20.0),
        "map": map_data
    })
