from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import struct
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

MAP_CONVERSION_SETTINGS = {
    "fuel": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "fuel_quantity": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "injection_timing": {"data_type": "8bit", "factor": 0.235, "offset": -20.0, "x_scale": 1.0, "y_scale": 20.0},
    "boost_pressure": {"data_type": "8bit", "factor": 15.686, "offset": -1000, "x_scale": 1.0, "y_scale": 20.0},
    "rail_pressure": {"data_type": "16bit", "factor": 0.02749, "offset": 0, "endian": "<H", "x_scale": 1.0, "y_scale": 20.0},
    "torque_limiter": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "drivers_wish": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "turbo_duty": {"data_type": "8bit", "factor": 0.392, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "smoke_limiter": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "iat_ect_correction": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "egr": {"data_type": "8bit", "factor": 0.392, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "throttle": {"data_type": "8bit", "factor": 0.392, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "dtc_off": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 1.0}
}

MAP_OFFSETS = {
    "fuel": {"block": 0x1D8710, "x_axis": 0x1D8610, "y_axis": 0x1D8600},
    "fuel_quantity": {"block": 0x1DC000, "x_axis": 0x1DBF10, "y_axis": 0x1DBF00},
    "injection_timing": {"block": 0x1DD000, "x_axis": 0x1DCF10, "y_axis": 0x1DCF00},
    "boost_pressure": {"block": 0x1DE000, "x_axis": 0x1DDF10, "y_axis": 0x1DDF00},
    "rail_pressure": {"block": 0x1DF000, "x_axis": 0x1DEF10, "y_axis": 0x1DEF00},
    "torque_limiter": {"block": 0x1DA000, "x_axis": 0x1D9F10, "y_axis": 0x1D9F00},
    "drivers_wish": {"block": 0x1DB020, "x_axis": 0x1DAF10, "y_axis": 0x1DAF00},
    "turbo_duty": {"block": 0x1E0010, "x_axis": 0x1DFF10, "y_axis": 0x1DFF00},
    "smoke_limiter": {"block": 0x1E1000, "x_axis": 0x1E0F10, "y_axis": 0x1E0F00},
    "iat_ect_correction": {"block": 0x1E2000, "x_axis": 0x1E1F10, "y_axis": 0x1E1F00},
    "egr": {"block": 0x1E3000, "x_axis": 0x1E2F10, "y_axis": 0x1E2F00},
    "throttle": {"block": 0x1E4020, "x_axis": 0x1E3F10, "y_axis": 0x1E3F00},
    "dtc_off": {"block": 0x1F0000, "x_axis": 0x1EFF10, "y_axis": 0x1EFF00}
}

def parse_axis(raw_bytes, scale):
    return [round(b * scale) for b in raw_bytes]

# === START OF CORRECTED INDENTATION ===

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "ECU Map Analyzer"}), 200

@app.route("/analyze", methods=["POST"])
def analyze_bin():
    if 'bin' not in request.files:
        app.logger.error("No file uploaded in the request.") # เพิ่ม logging
        return jsonify({"error": "No file uploaded"}), 400

    map_type = (request.form.get('type') or 'fuel').lower()
    if map_type not in MAP_OFFSETS:
        app.logger.error(f"Unsupported map type requested: {map_type}") # เพิ่ม logging
        return jsonify({"error": f"Unsupported map type: {map_type}"}), 400

    try:
        bin_file = request.files['bin']
        content = bin_file.read()
        offsets = MAP_OFFSETS[map_type]
        conv = MAP_CONVERSION_SETTINGS[map_type]

        data_type = conv["data_type"]
        value_size = 2 if data_type == "16bit" else 1
        map_byte_size = 16 * 16 * value_size
        required_size = max(offsets["block"] + map_byte_size,
                            offsets["x_axis"] + 16,
                            offsets["y_axis"] + 16)

        if len(content) < required_size:
            app.logger.error(f"File too small for map '{map_type}'. File size: {len(content)}, Required: {required_size}") # เพิ่ม logging
            return jsonify({"error": "File too small for this map"}), 400

        x_axis_raw_bytes = content[offsets["x_axis"]:offsets["x_axis"] + 16]
        y_axis_raw_bytes = content[offsets["y_axis"]:offsets["y_axis"] + 16]

        # เพิ่มการตรวจสอบขนาดของ Axis bytes เพื่อ robustness
        if len(x_axis_raw_bytes) < 16:
            app.logger.warning(f"X-axis raw bytes for {map_type} is less than 16 bytes. Actual: {len(x_axis_raw_bytes)}")
        if len(y_axis_raw_bytes) < 16:
            app.logger.warning(f"Y-axis raw bytes for {map_type} is less than 16 bytes. Actual: {len(y_axis_raw_bytes)}")

        x_axis = parse_axis(x_axis_raw_bytes, conv["x_scale"])
        y_axis = parse_axis(y_axis_raw_bytes, conv["y_scale"])
        block_raw = content[offsets["block"]:offsets["block"] + map_byte_size]
        factor = conv["factor"]
        offset_val = conv["offset"]
        endian = conv.get("endian") # ใช้ .get() เพื่อให้เป็น None ถ้าไม่มี key

        # ตรวจ byte ซ้ำ
        if block_raw and all(b == block_raw[0] for b in block_raw): # เพิ่ม check block_raw ว่าไม่ว่าง
            app.logger.warning(f"{map_type.upper()} map block byte ซ้ำทั้งหมด: {block_raw[0]} (Offset: {hex(offsets['block'])})")

        map_2d = []
        for i in range(16):
            row = []
            for j in range(16):
                raw = 0 # Default raw value
                value = None # Default value for processed value

                if data_type == "8bit":
                    idx = i * 16 + j
                    if idx < len(block_raw): # ตรวจสอบขอบเขต
                        raw = block_raw[idx]
                        value = raw * factor + offset_val
                    else:
                        app.logger.warning(f"8bit map '{map_type}' out of bounds at [{i},{j}]. Block length: {len(block_raw)}")

                elif data_type == "16bit":
                    idx = (i * 16 + j) * 2
                    if idx + 1 < len(block_raw): # ตรวจสอบขอบเขต 2 ไบต์
                        value_bytes = block_raw[idx:idx + 2]
                        if endian is None: # ตรวจสอบว่ามี endian กำหนดหรือไม่
                            app.logger.error(f"16bit map '{map_type}' requires 'endian' in conversion settings but it's missing.")
                            value = None # ไม่สามารถ unpack ได้ถ้าไม่มี endian
                        else:
                            try:
                                raw = struct.unpack(endian, value_bytes)[0]
                                value = raw * factor + offset_val
                            except struct.error:
                                app.logger.error(f"Struct unpack error for 16bit map '{map_type}' at index {idx}. Bytes: {value_bytes.hex()}, Endian: {endian}")
                                value = None # Set to None on unpack error
                    else:
                        app.logger.warning(f"16bit map '{map_type}' out of bounds at [{i},{j}]. Block length: {len(block_raw)}")

                # Special handling for negative values (as before, but more robust with None)
                if value is not None and map_type in ["boost_pressure", "turbo_duty", "throttle"] and value < 0:
                    value = 0 # เปลี่ยนเป็น 0 แทน None ถ้าเป็นค่าติดลบที่ควรจะเป็นบวก

                row.append(round(value, 2) if value is not None else None) # ใช้ None ถ้า value เป็น None
            map_2d.append(row)

        app.logger.info(f"Successfully analyzed '{map_type}' map ({data_type}). Dimensions: {len(map_2d)}x{len(map_2d[0]) if map_2d else 0}")
        return jsonify({
            "type": map_type,
            "display_name": get_map_display_name(map_type),
            "offset": hex(offsets["block"]),
            "x_axis": x_axis,
            "y_axis": y_axis,
            "unit": get_map_unit(map_type),
            "map": map_2d
        })

    except Exception as e:
        app.logger.exception(f"Error analyzing {map_type}. Details: {e}")
        return jsonify({"error": str(e)}), 500

# ฟังก์ชัน get_map_display_name และ get_map_unit ต้องอยู่ระดับเดียวกับฟังก์ชัน Flask route
def get_map_display_name(map_type):
    names = {
        "fuel": "Limit IQ (Fuel Map)",
        "fuel_quantity": "Injector Quantity",
        "injection_timing": "Injector Timing",
        "boost_pressure": "Boost Pressure",
        "rail_pressure": "Rail Pressure (Limit CRP)",
        "torque_limiter": "Limit Torque",
        "drivers_wish": "Torque TPS (Driver’s Wish)",
        "turbo_duty": "Turbo Duty Cycle",
        "smoke_limiter": "Smoke Limiter",
        "iat_ect_correction": "IAT & ECT Correction",
        "egr": "EGR Target",
        "throttle": "Throttle Valve",
        "dtc_off": "DTC Table"
    }
    return names.get(map_type, map_type)

def get_map_unit(map_type):
    units = {
        "fuel": "mg/stroke",
        "fuel_quantity": "mg/stroke",
        "injection_timing": "° BTDC",
        "boost_pressure": "mbar",
        "rail_pressure": "bar",
        "torque_limiter": "%",
        "drivers_wish": "%",
        "turbo_duty": "%",
        "smoke_limiter": "mg/stroke",
        "iat_ect_correction": "%",
        "egr": "%",
        "throttle": "%",
        "dtc_off": ""
    }
    return units.get(map_type, "")

# ถ้าต้องการรันในเครื่องตัวเอง
# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=10000, debug=True)
