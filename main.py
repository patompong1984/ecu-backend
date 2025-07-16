from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import struct
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024 # เพิ่มขนาดไฟล์
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# MAP_OFFSETS ใหม่ ที่ระบุ offset ของ block และ x_axis, y_axis ด้วย
# และควรระบุขนาด (rows, cols) ของ map block
# รวมถึง offset ของแกน X และ Y
MAP_OFFSETS = {
    # ตัวอย่าง:
    # "map_name": {"block": 0xADDRESS_OF_MAP, "x_axis": 0xADDRESS_OF_X_AXIS, "y_axis": 0xADDRESS_OF_Y_AXIS, "size": (ROWS, COLS)},
    # หมายเหตุ: คุณจะต้องหา offset ของแกน X และ Y ของแต่ละ map ด้วยตัวเอง
    # หาก Map นั้นมีแกน X/Y เฉพาะ (ซึ่งส่วนใหญ่จะมี)
    # ถ้าไม่มี x_axis / y_axis key แสดงว่าใช้ default/สร้างเอง หรือเป็น 1D map
    "limit_iq_1": {"block": 0x141918, "x_axis": 0x141886, "y_axis": 0x1418D8, "size": (26, 21)}, # ตัวอย่าง offset แกนที่อาจต้องปรับ
    "limit_iq_2": {"block": 0x141D5C, "x_axis": 0x141CC6, "y_axis": 0x141D18, "size": (26, 21)},
    "limit_iq_3": {"block": 0x1421A0, "x_axis": 0x14210A, "y_axis": 0x14215C, "size": (26, 21)},
    "torque_tps_1": {"block": 0x143FA6, "x_axis": 0x143F10, "y_axis": 0x143F62, "size": (26, 21)},
    "torque_tps_2": {"block": 0x1633A0, "x_axis": 0x16330A, "y_axis": 0x16335C, "size": (26, 21)},
    "torque_tps_3": {"block": 0x16571A, "x_axis": 0x165684, "y_axis": 0x1656D6, "size": (26, 21)},
    "egr_target": {"block": 0x148E36, "x_axis": 0x148DB6, "y_axis": 0x148DF8, "size": (21, 11)},
    "pump_command": {"block": 0x14DD54, "x_axis": 0x14DCC4, "y_axis": 0x14DD00, "size": (21, 15)},
    "injector_1": {"block": 0x161560, "x_axis": 0x161470, "y_axis": 0x1614F0, "size": (14, 25)},
    "injector_2": {"block": 0x161840, "x_axis": 0x161750, "y_axis": 0x1617D0, "size": (14, 25)},
    "limit_baro_1": {"block": 0x166176, "x_axis": 0x1660A8, "y_axis": 0x166120, "size": (23, 10)},
    "limit_baro_2": {"block": 0x16635A, "x_axis": 0x1662EE, "y_axis": 0x166324, "size": (23, 5)},
    "limit_baro_3": {"block": 0x160526, "x_axis": 0x1604BA, "y_axis": 0x1604F0, "size": (23, 5)},
    "limit_torque": {"block": 0x167002, "x_axis": 0x166F34, "y_axis": 0x166FA6, "size": (23, 10)},
    "torque_gear": {"block": 0x1681A, "x_axis": 0x1678A, "y_axis": 0x167E0, "size": (25, 6)}, # อาจจะต้องปรับ offset แกน
    "limit_crp": {"block": 0x1957C2, "x_axis": 0x195726, "y_axis": 0x19577A, "size": (26, 20)},
    "green_1": {"block": 0x1958C0, "x_axis": 0x195824, "y_axis": 0x195878, "size": (26, 20)},
    "green_2": {"block": 0x195915, "x_axis": 0x195879, "y_axis": 0x1958CD, "size": (26, 20)},
    "green_3": {"block": 0x195A56, "x_axis": 0x1959BA, "y_axis": 0x195A0C, "size": (26, 20)},
    "green_4": {"block": 0x1970E, "x_axis": 0x19672, "y_axis": 0x196C4, "size": (21, 20)},
    "green_5": {"block": 0x197475, "x_axis": 0x1973DE, "y_axis": 0x197430, "size": (25, 20)},
    "turbo": {"block": 0x19541C, "x_axis": 0x19535A, "y_axis": 0x1953D4, "size": (21, 14)},
    "turbo_meter": {"block": 0x195E62, "x_axis": 0x195DE8, "y_axis": 0x195E2C, "size": (21, 9)},
    "dtc_off": {"block": 0x1D0018, "x_axis": 0x1D0000, "y_axis": 0x1D0008, "size": (5, 25)} # อาจจะต้องปรับ offset แกน
}

# MAP_CONVERSION_SETTINGS พร้อมการตั้งค่าสำหรับแต่ละ Map โดยเฉพาะ
# หรือการกำหนด default สำหรับ map ที่ยังไม่มีข้อมูลที่ชัดเจน
MAP_CONVERSION_SETTINGS = {
    # Default settings (ควรมี)
    "default_8bit": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "default_16bit": {"data_type": "16bit", "factor": 1.0, "offset": 0, "endian": "<H", "x_scale": 1.0, "y_scale": 1.0},
    # Specific map settings (ตัวอย่าง)
    "limit_iq_1": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "limit_iq_2": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "limit_iq_3": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "torque_tps_1": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "torque_tps_2": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "torque_tps_3": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "egr_target": {"data_type": "8bit", "factor": 0.392, "offset": 0, "x_scale": 100.0, "y_scale": 20.0}, # Example scales
    "pump_command": {"data_type": "16bit", "factor": 0.02749, "offset": 0, "endian": "<H", "x_scale": 10.0, "y_scale": 100.0},
    "injector_1": {"data_type": "16bit", "factor": 0.01, "offset": 0, "endian": "<H", "x_scale": 0.235, "y_scale": 20.0},
    "injector_2": {"data_type": "16bit", "factor": 0.01, "offset": 0, "endian": "<H", "x_scale": 0.235, "y_scale": 20.0},
    "limit_baro_1": {"data_type": "8bit", "factor": 15.686, "offset": -1000, "x_scale": 1.0, "y_scale": 1.0},
    "limit_baro_2": {"data_type": "8bit", "factor": 15.686, "offset": -1000, "x_scale": 1.0, "y_scale": 1.0},
    "limit_baro_3": {"data_type": "8bit", "factor": 15.686, "offset": -1000, "x_scale": 1.0, "y_scale": 1.0},
    "limit_torque": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "torque_gear": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "limit_crp": {"data_type": "16bit", "factor": 0.02749, "offset": 0, "endian": "<H", "x_scale": 1.0, "y_scale": 1.0},
    "green_1": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "green_2": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "green_3": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "green_4": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "green_5": {"data_type": "8bit", "factor": 0.235, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "turbo": {"data_type": "8bit", "factor": 0.392, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "turbo_meter": {"data_type": "8bit", "factor": 0.392, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "dtc_off": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 1.0}
}

# ฟังก์ชันสำหรับแปลงค่าแกน (ใช้กับ raw bytes)
def parse_axis_values(raw_bytes, scale, data_type="8bit", endian=None):
    values = []
    if data_type == "8bit":
        for b in raw_bytes:
            values.append(round(b * scale, 2))
    elif data_type == "16bit" and endian:
        for i in range(0, len(raw_bytes), 2):
            if i + 1 < len(raw_bytes):
                try:
                    raw = struct.unpack(endian, raw_bytes[i:i+2])[0]
                    values.append(round(raw * scale, 2))
                except struct.error:
                    logging.warning(f"Struct unpack error for axis at index {i}. Bytes: {raw_bytes[i:i+2].hex()}")
                    values.append(None)
            else:
                logging.warning(f"Incomplete bytes for 16bit axis at index {i}.")
                values.append(None)
    return values

# Helper functions for display names and units
def get_map_display_name(map_type):
    names = {
        "limit_iq_1": "Limit IQ 1",
        "limit_iq_2": "Limit IQ 2",
        "limit_iq_3": "Limit IQ 3",
        "torque_tps_1": "Torque TPS 1 (Driver’s Wish)",
        "torque_tps_2": "Torque TPS 2",
        "torque_tps_3": "Torque TPS 3",
        "egr_target": "EGR Target",
        "pump_command": "Pump Command (Injection Quantity)",
        "injector_1": "Injector Map 1 (Duration)",
        "injector_2": "Injector Map 2 (Duration)",
        "limit_baro_1": "Limit Barometric Pressure 1",
        "limit_baro_2": "Limit Barometric Pressure 2",
        "limit_baro_3": "Limit Barometric Pressure 3",
        "limit_torque": "Limit Torque",
        "torque_gear": "Torque Gear Correction",
        "limit_crp": "Rail Pressure Limit (CRP)",
        "green_1": "Fuel Map Green 1",
        "green_2": "Fuel Map Green 2",
        "green_3": "Fuel Map Green 3",
        "green_4": "Fuel Map Green 4",
        "green_5": "Fuel Map Green 5",
        "turbo": "Turbo Boost Map",
        "turbo_meter": "Turbo Metering Map",
        "dtc_off": "DTC Off Table"
    }
    return names.get(map_type, map_type.replace('_', ' ').title())

def get_map_unit(map_type):
    units = {
        "limit_iq_1": "mg/stroke",
        "limit_iq_2": "mg/stroke",
        "limit_iq_3": "mg/stroke",
        "torque_tps_1": "%",
        "torque_tps_2": "%",
        "torque_tps_3": "%",
        "egr_target": "%",
        "pump_command": "bar", # หรือ mg/stroke ขึ้นอยู่กับ ECU
        "injector_1": "° BTDC", # หรือ ms
        "injector_2": "° BTDC", # หรือ ms
        "limit_baro_1": "mbar",
        "limit_baro_2": "mbar",
        "limit_baro_3": "mbar",
        "limit_torque": "Nm", # หรือ %
        "torque_gear": "Nm", # หรือ %
        "limit_crp": "bar",
        "green_1": "mg/stroke",
        "green_2": "mg/stroke",
        "green_3": "mg/stroke",
        "green_4": "mg/stroke",
        "green_5": "mg/stroke",
        "turbo": "mbar", # หรือ % duty
        "turbo_meter": "mbar", # หรือ % duty
        "dtc_off": ""
    }
    return units.get(map_type, "")

# Health Check Route (เพิ่มกลับมา)
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "ECU Map Analyzer"}), 200

# Main Analysis Route
@app.route("/analyze", methods=["POST"])
def analyze_dynamic_map():
    if 'bin' not in request.files:
        logging.error("No file uploaded in the request.")
        return jsonify({"error": "No file uploaded"}), 400

    map_type = request.form.get("type")
    if map_type not in MAP_OFFSETS:
        logging.error(f"Unsupported map type: {map_type}")
        return jsonify({"error": f"Unsupported map type: {map_type}"}), 400

    map_info = MAP_OFFSETS[map_type]
    block_offset = map_info["block"]
    rows, cols = map_info["size"]
    x_axis_offset = map_info.get("x_axis")
    y_axis_offset = map_info.get("y_axis")

    # ดึง conversion settings สำหรับ map_type นั้นๆ หรือใช้ default
    conv = MAP_CONVERSION_SETTINGS.get(map_type)
    if not conv: # ถ้าไม่มีการตั้งค่าเฉพาะสำหรับ map นี้
        # ตรวจสอบว่าควรใช้ 8bit หรือ 16bit default
        # อาจจะต้องมีวิธีระบุใน MAP_OFFSETS หรือตั้งค่า logic อื่นๆ
        # สำหรับตอนนี้ จะสมมติว่าถ้าไม่มีใน MAP_CONVERSION_SETTINGS_SPECIFIC จะใช้ default_8bit
        # หรือถ้า map_type ที่รู้จักกันดีว่าเป็น 16bit (เช่น pump_command, injector, limit_crp)
        # ให้ใช้ default_16bit
        if map_type in ["pump_command", "injector_1", "injector_2", "limit_crp"]:
             conv = MAP_CONVERSION_SETTINGS["default_16bit"]
             logging.info(f"Using default_16bit for {map_type}")
        else:
            conv = MAP_CONVERSION_SETTINGS["default_8bit"]
            logging.info(f"Using default_8bit for {map_type}")
    
    data_type = conv["data_type"]
    factor = conv["factor"]
    offset_val = conv["offset"]
    endian = conv.get("endian")
    x_scale = conv.get("x_scale", 1.0) # ใช้ค่าจาก conv_settings หรือ default
    y_scale = conv.get("y_scale", 1.0) # ใช้ค่าจาก conv_settings หรือ default


    byte_per_value = 2 if data_type == "16bit" else 1
    total_map_bytes = rows * cols * byte_per_value

    # คำนวณขนาดไฟล์ที่ต้องการทั้งหมด
    required_size = block_offset + total_map_bytes
    if x_axis_offset is not None:
        required_size = max(required_size, x_axis_offset + cols * (2 if data_type == "16bit_axis" else 1)) # สมมติ 8bit axis หรือ 16bit axis
    if y_axis_offset is not None:
        required_size = max(required_size, y_axis_offset + rows * (2 if data_type == "16bit_axis" else 1)) # สมมติ 8bit axis หรือ 16bit axis

    try:
        bin_file = request.files["bin"]
        content = bin_file.read()

        if len(content) < required_size:
            logging.error(f"File too small for map '{map_type}'. File size: {len(content)}, Required: {required_size}")
            return jsonify({"error": "File too small for selected map"}), 400

        # Read map block
        raw_block = content[block_offset : block_offset + total_map_bytes]
        if not raw_block or len(raw_block) < total_map_bytes: # ตรวจสอบขนาดของ block_raw อีกครั้ง
            logging.error(f"Incomplete raw block for map '{map_type}'. Read {len(raw_block)} bytes, expected {total_map_bytes}.")
            return jsonify({"error": "Incomplete map data in file"}), 400

        # ตรวจ byte ซ้ำ
        if all(b == raw_block[0] for b in raw_block):
            logging.warning(f"{map_type.upper()} map block byte ซ้ำทั้งหมด: {raw_block[0]} (Offset: {hex(block_offset)})")

        map_data = []
        for i in range(rows):
            row = []
            for j in range(cols):
                raw_value = 0
                processed_value = None
                
                start_idx = (i * cols + j) * byte_per_value
                end_idx = start_idx + byte_per_value

                if end_idx > len(raw_block):
                    logging.warning(f"Map data out of bounds for {map_type} at [{i},{j}]. Expected idx {start_idx}, block length {len(raw_block)}")
                    processed_value = None # หรืออาจจะ 0 แล้วแต่ต้องการ
                    row.append(processed_value)
                    continue

                if data_type == "8bit":
                    raw_value = raw_block[start_idx]
                elif data_type == "16bit":
                    if endian is None:
                        logging.error(f"16bit map '{map_type}' requires 'endian' in conversion settings but it's missing.")
                        row.append(None)
                        continue
                    try:
                        raw_value = struct.unpack(endian, raw_block[start_idx:end_idx])[0]
                    except struct.error as se:
                        logging.error(f"Struct unpack error for 16bit map '{map_type}' at index {start_idx}. Bytes: {raw_block[start_idx:end_idx].hex()}, Endian: {endian}. Error: {se}")
                        row.append(None)
                        continue
                else: # Unknown data_type
                    logging.error(f"Unknown data_type '{data_type}' for map '{map_type}'.")
                    row.append(None)
                    continue

                processed_value = raw_value * factor + offset_val
                
                # Special handling for negative values (e.g., pressure, duty cycle should not be negative)
                if processed_value is not None and map_type in ["turbo", "turbo_meter", "limit_baro_1", "limit_baro_2", "limit_baro_3"] and processed_value < 0:
                    processed_value = 0

                row.append(round(processed_value, 2) if processed_value is not None else None)
            map_data.append(row)

        # Read and parse X and Y axes
        x_axis = []
        y_axis = []
        
        # สมมติว่าแกน X และ Y เป็น 8bit หรือ 16bit เช่นเดียวกับ map block หรืออาจจะต้องกำหนดแยก
        # สำหรับ Isuzu D-Max 1.9L มักจะเป็น 8bit สำหรับแกน X/Y
        axis_data_type = "8bit" # หรือ "16bit" ถ้า Map นั้นใช้ 16bit axis
        axis_endian = None # "<H" ถ้าเป็น 16bit axis

        if x_axis_offset is not None:
            # สมมติว่าแกน X มีขนาดเท่ากับจำนวนคอลัมน์ของ Map
            x_axis_raw_bytes_len = cols * (2 if axis_data_type == "16bit" else 1)
            x_axis_raw_bytes = content[x_axis_offset : x_axis_offset + x_axis_raw_bytes_len]
            x_axis = parse_axis_values(x_axis_raw_bytes, x_scale, axis_data_type, axis_endian)
            if len(x_axis) > cols: # trim excess if axis is longer than map dimensions
                x_axis = x_axis[:cols]
        else:
            # Fallback if x_axis_offset is not provided: generate generic axis
            x_axis = [round(i * x_scale, 2) for i in range(cols)]
            logging.warning(f"X-axis offset not found for {map_type}. Generating generic X-axis.")

        if y_axis_offset is not None:
            # สมมติว่าแกน Y มีขนาดเท่ากับจำนวนแถวของ Map
            y_axis_raw_bytes_len = rows * (2 if axis_data_type == "16bit" else 1)
            y_axis_raw_bytes = content[y_axis_offset : y_axis_offset + y_axis_raw_bytes_len]
            y_axis = parse_axis_values(y_axis_raw_bytes, y_scale, axis_data_type, axis_endian)
            if len(y_axis) > rows: # trim excess if axis is longer than map dimensions
                y_axis = y_axis[:rows]
        else:
            # Fallback if y_axis_offset is not provided: generate generic axis
            y_axis = [round(i * y_scale, 2) for i in range(rows)]
            logging.warning(f"Y-axis offset not found for {map_type}. Generating generic Y-axis.")
            
        # ตรวจสอบขนาดของแกนอีกครั้ง ถ้าไม่ตรง ให้เติมหรือตัด
        while len(x_axis) < cols:
            x_axis.append(None)
        while len(x_axis) > cols:
            x_axis.pop()

        while len(y_axis) < rows:
            y_axis.append(None)
        while len(y_axis) > rows:
            y_axis.pop()


        logging.info(f"Successfully analyzed '{map_type}' map ({data_type}). Dimensions: {rows}x{cols}")
        return jsonify({
            "type": map_type,
            "display_name": get_map_display_name(map_type),
            "offset": hex(block_offset),
            "x_axis": x_axis,
            "y_axis": y_axis,
            "unit": get_map_unit(map_type),
            "map": map_data
        })

    except Exception as e:
        logging.exception(f"Error analyzing {map_type}. Details: {e}")
        return jsonify({"error": str(e)}), 500

# If running locally for development
# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=10000, debug=True)
