from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import logging
import struct
import io
import json
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s') # ปรับปรุง format ของ log
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ==============================================================================
# MAP DEFINITIONS - Critical for accurate map analysis
#
# สำคัญมาก: Offsets และ Sizes เหล่านี้ต้องถูกต้องสำหรับไฟล์ .bin เฉพาะรุ่น/เวอร์ชัน
# ที่คุณกำลังวิเคราะห์
# หากค่าเหล่านี้ไม่ถูกต้อง กราฟจะผิดเพี้ยน หรือเกิดข้อผิดพลาด "File too small"
# หรือ "Incomplete map data"
#
# คุณจำเป็นต้องหาค่าที่ถูกต้องจากแหล่งข้อมูลที่เชื่อถือได้ เช่น Damos files,
# ซอฟต์แวร์ Tuning เฉพาะทาง (WinOLS, TunerPro RT), หรือการทำ Reverse Engineering
# ด้วย Hex Editor (เปรียบเทียบไฟล์)
# ==============================================================================
MAP_OFFSETS = {
    # รูปแบบ: "map_name": {"block": 0xADDRESS_OF_MAP, "x_axis": 0xADDRESS_OF_X_AXIS, "y_axis": 0xADDRESS_OF_Y_AXIS, "size": (ROWS, COLS)},
    # ถ้า Map นั้นไม่มีแกน X/Y เฉพาะเจาะจง สามารถละเว้น "x_axis" หรือ "y_axis" ได้
    # หรือถ้าเป็น 1D map (แถวเดียวหรือคอลัมน์เดียว) ให้ปรับ size ให้ถูกต้อง
    "limit_iq_1": {"block": 0x141918, "x_axis": 0x141886, "y_axis": 0x1418D8, "size": (26, 21)},
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
    "torque_gear": {"block": 0x1681A, "x_axis": 0x1678A, "y_axis": 0x167E0, "size": (25, 6)},
    "limit_crp": {"block": 0x1957C2, "x_axis": 0x195726, "y_axis": 0x19577A, "size": (26, 20)},
    "green_1": {"block": 0x1958C0, "x_axis": 0x195824, "y_axis": 0x195878, "size": (26, 20)},
    "green_2": {"block": 0x195915, "x_axis": 0x195879, "y_axis": 0x1958CD, "size": (26, 20)},
    "green_3": {"block": 0x195A56, "x_axis": 0x1959BA, "y_axis": 0x195A0C, "size": (26, 20)},
    "green_4": {"block": 0x1970E, "x_axis": 0x19672, "y_axis": 0x196C4, "size": (21, 20)},
    "green_5": {"block": 0x197475, "x_axis": 0x1973DE, "y_axis": 0x197430, "size": (25, 20)},
    "turbo": {"block": 0x19541C, "x_axis": 0x19535A, "y_axis": 0x1953D4, "size": (21, 14)},
    "turbo_meter": {"block": 0x195E62, "x_axis": 0x195DE8, "y_axis": 0x195E2C, "size": (21, 9)},
    "dtc_off": {"block": 0x1D0018, "x_axis": 0x1D0000, "y_axis": 0x1D0008, "size": (5, 25)}
}

# ==============================================================================
# MAP CONVERSION SETTINGS - Defines how raw bytes are converted to human-readable values
#
# ค่า factor, offset, data_type, endian, x_scale, y_scale มีผลโดยตรงต่อการแสดงผล
# ที่ถูกต้อง หากค่าเหล่านี้ผิด กราฟจะออกมาผิดเพี้ยน หรือค่าไม่สมเหตุสมผล
# ==============================================================================
MAP_CONVERSION_SETTINGS = {
    # Default settings: ใช้เมื่อไม่มีการตั้งค่าเฉพาะสำหรับ Map นั้นๆ
    "default_8bit": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 1.0},
    "default_16bit": {"data_type": "16bit", "factor": 1.0, "offset": 0, "endian": "<H", "x_scale": 1.0, "y_scale": 1.0}, # <H = Little-endian Unsigned Short

    # Specific map settings: ปรับค่าเหล่านี้ตามข้อมูล Damos หรือการวิเคราะห์ของคุณ
    "limit_iq_1": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "limit_iq_2": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "limit_iq_3": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "torque_tps_1": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "torque_tps_2": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "torque_tps_3": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 0.235, "y_scale": 20.0},
    "egr_target": {"data_type": "8bit", "factor": 0.392, "offset": 0, "x_scale": 100.0, "y_scale": 20.0},
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
    bytes_per_axis_value = 2 if data_type == "16bit" else 1

    for i in range(0, len(raw_bytes), bytes_per_axis_value):
        if i + bytes_per_axis_value > len(raw_bytes):
            logging.warning(f"Incomplete bytes for {data_type} axis value at index {i}. Skipping.")
            values.append(None)
            continue

        raw_value = None
        if data_type == "8bit":
            raw_value = raw_bytes[i]
        elif data_type == "16bit":
            if endian is None:
                logging.error(f"16bit axis requires 'endian' in conversion settings but it's missing.")
                values.append(None)
                continue
            try:
                raw_value = struct.unpack(endian, raw_bytes[i:i+bytes_per_axis_value])[0]
            except struct.error as se:
                logging.error(f"Struct unpack error for 16bit axis at index {i}. Bytes: {raw_bytes[i:i+bytes_per_axis_value].hex()}, Endian: {endian}. Error: {se}")
                values.append(None)
                continue
        else:
            logging.error(f"Unknown data_type '{data_type}' for axis.")
            values.append(None)
            continue
        
        if raw_value is not None:
            values.append(round(raw_value * scale, 2))
        else:
            values.append(None) # ในกรณีที่ raw_value เป็น None จาก error ก่อนหน้า
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

# Health Check Route
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
        return jsonify({"error": f"Unsupported map type: {map_type}. Please check MAP_OFFSETS configuration."}), 400 # เพิ่มข้อความแนะนำ

    map_info = MAP_OFFSETS[map_type]
    block_offset = map_info["block"]
    rows, cols = map_info["size"]
    x_axis_offset = map_info.get("x_axis")
    y_axis_offset = map_info.get("y_axis")

    # ดึง conversion settings สำหรับ map_type นั้นๆ หรือใช้ default
    conv = MAP_CONVERSION_SETTINGS.get(map_type)
    if not conv:
        if map_type in ["pump_command", "injector_1", "injector_2", "limit_crp"]:
             conv = MAP_CONVERSION_SETTINGS["default_16bit"]
             logging.info(f"Using default_16bit for {map_type} (no specific settings found).")
        else:
            conv = MAP_CONVERSION_SETTINGS["default_8bit"]
            logging.info(f"Using default_8bit for {map_type} (no specific settings found).")
    
    data_type = conv["data_type"]
    factor = conv["factor"]
    offset_val = conv["offset"]
    endian = conv.get("endian")
    x_scale = conv.get("x_scale", 1.0)
    y_scale = conv.get("y_scale", 1.0)

    # กำหนด data_type และ endian สำหรับแกน X/Y โดยเฉพาะ (หากไม่ได้กำหนดใน conv_settings จะใช้ของ Map block)
    axis_x_data_type = conv.get("x_axis_data_type", data_type)
    axis_x_endian = conv.get("x_axis_endian", endian)
    axis_y_data_type = conv.get("y_axis_data_type", data_type)
    axis_y_endian = conv.get("y_axis_endian", endian)
    axis_x_scale = conv.get("x_axis_scale", x_scale) # ใช้ scale เฉพาะแกนถ้ามี หรือใช้ x_scale ของ Map
    axis_y_scale = conv.get("y_axis_scale", y_scale) # ใช้ scale เฉพาะแกนถ้ามี หรือใช้ y_scale ของ Map

    byte_per_value = 2 if data_type == "16bit" else 1
    total_map_bytes = rows * cols * byte_per_value

    # คำนวณขนาดไฟล์ที่ต้องการทั้งหมด เพื่อตรวจสอบ File too small
    required_size = block_offset + total_map_bytes
    if x_axis_offset is not None:
        required_size = max(required_size, x_axis_offset + cols * (2 if axis_x_data_type == "16bit" else 1)) 
    if y_axis_offset is not None:
        required_size = max(required_size, y_axis_offset + rows * (2 if axis_y_data_type == "16bit" else 1)) 

    try:
        bin_file = request.files["bin"]
        content = bin_file.read()

        if len(content) < required_size:
            logging.error(f"File too small for map '{map_type}'. File size: {len(content)} bytes, Required: {required_size} bytes. Check MAP_OFFSETS or use correct BIN file.")
            return jsonify({"error": f"File too small for selected map. Expected at least {required_size} bytes, got {len(content)} bytes. Please check the BIN file or map offsets."}), 400

        # Read map block
        # ตรวจสอบขอบเขตการอ่านก่อน
        if block_offset + total_map_bytes > len(content):
            logging.error(f"Map block read out of bounds for '{map_type}'. Offset: {hex(block_offset)}, Expected end: {hex(block_offset + total_map_bytes)}, File size: {hex(len(content))}.")
            return jsonify({"error": "Map data out of file bounds. Check map block offset and size."}), 400

        raw_block = content[block_offset : block_offset + total_map_bytes]
        if len(raw_block) != total_map_bytes: # ตรวจสอบขนาดของ block_raw อีกครั้ง
            logging.error(f"Incomplete raw block for map '{map_type}'. Read {len(raw_block)} bytes, expected {total_map_bytes}. Check map size.")
            return jsonify({"error": "Incomplete map data in file. Check map dimensions."}), 400

        # ตรวจสอบ byte ซ้ำ (อาจบ่งบอก Map ว่างเปล่าหรือ Offset ผิด)
        if all(b == raw_block[0] for b in raw_block) and raw_block: # เพิ่ม raw_block: เพื่อป้องกัน list ว่าง
            logging.warning(f"{map_type.upper()} map block contains all identical bytes: {raw_block[0]} (Offset: {hex(block_offset)}). This might indicate an incorrect offset or an empty/null map.")

        map_data = []
        for i in range(rows):
            row = []
            for j in range(cols):
                raw_value = None
                
                start_idx = (i * cols + j) * byte_per_value
                end_idx = start_idx + byte_per_value

                if end_idx > len(raw_block):
                    logging.warning(f"Map data out of bounds for {map_type} at [{i},{j}]. Block read {len(raw_block)} bytes, Expected idx {start_idx}. Filling with None.")
                    processed_value = None
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
                        logging.error(f"Struct unpack error for 16bit map '{map_type}' at index {start_idx}. Bytes: {raw_block[start_idx:end_idx].hex()}, Endian: {endian}. Error: {se}. Filling with None.")
                        row.append(None)
                        continue
                else:
                    logging.error(f"Unknown data_type '{data_type}' for map '{map_type}'. Filling with None.")
                    row.append(None)
                    continue

                processed_value = None
                if raw_value is not None:
                    processed_value = raw_value * factor + offset_val
                
                    # Special handling for negative values (e.g., pressure, duty cycle should not be negative)
                    if map_type in ["turbo", "turbo_meter", "limit_baro_1", "limit_baro_2", "limit_baro_3"] and processed_value < 0:
                        processed_value = 0 # Clamp to 0 if it's a pressure/duty cycle map

                row.append(round(processed_value, 2) if processed_value is not None else None)
            map_data.append(row)

        # Read and parse X and Y axes
        x_axis = []
        y_axis = []
        
        if x_axis_offset is not None:
            x_axis_raw_bytes_len = cols * (2 if axis_x_data_type == "16bit" else 1)
            # ตรวจสอบขอบเขตก่อนอ่านแกน X
            if x_axis_offset + x_axis_raw_bytes_len > len(content):
                logging.warning(f"X-axis read out of bounds for {map_type}. Offset: {hex(x_axis_offset)}, Expected end: {hex(x_axis_offset + x_axis_raw_bytes_len)}, File size: {hex(len(content))}. Generating generic X-axis.")
                x_axis = [round(i * axis_x_scale, 2) for i in range(cols)]
            else:
                x_axis_raw_bytes = content[x_axis_offset : x_axis_offset + x_axis_raw_bytes_len]
                x_axis = parse_axis_values(x_axis_raw_bytes, axis_x_scale, axis_x_data_type, axis_x_endian)
        else:
            x_axis = [round(i * axis_x_scale, 2) for i in range(cols)]
            logging.info(f"X-axis offset not specified for {map_type}. Generating generic X-axis with scale {axis_x_scale}.")

        if y_axis_offset is not None:
            y_axis_raw_bytes_len = rows * (2 if axis_y_data_type == "16bit" else 1)
            # ตรวจสอบขอบเขตก่อนอ่านแกน Y
            if y_axis_offset + y_axis_raw_bytes_len > len(content):
                logging.warning(f"Y-axis read out of bounds for {map_type}. Offset: {hex(y_axis_offset)}, Expected end: {hex(y_axis_offset + y_axis_raw_bytes_len)}, File size: {hex(len(content))}. Generating generic Y-axis.")
                y_axis = [round(i * axis_y_scale, 2) for i in range(rows)]
            else:
                y_axis_raw_bytes = content[y_axis_offset : y_axis_offset + y_axis_raw_bytes_len]
                y_axis = parse_axis_values(y_axis_raw_bytes, axis_y_scale, axis_y_data_type, axis_y_endian)
        else:
            y_axis = [round(i * axis_y_scale, 2) for i in range(rows)]
            logging.info(f"Y-axis offset not specified for {map_type}. Generating generic Y-axis with scale {axis_y_scale}.")
            
        # ตรวจสอบขนาดของแกนอีกครั้ง ถ้าไม่ตรง ให้เติมหรือตัด
        while len(x_axis) < cols:
            x_axis.append(None)
        while len(x_axis) > cols:
            x_axis.pop()

        while len(y_axis) < rows:
            y_axis.append(None)
        while len(y_axis) > rows:
            y_axis.pop()

        logging.info(f"Successfully analyzed '{map_type}' map ({data_type}). Dimensions: {rows}x{cols}. Block Offset: {hex(block_offset)}")
        return jsonify({
            "type": map_type,
            "display_name": get_map_display_name(map_type),
            "offset": hex(block_offset), # ส่ง offset เป็น hex string
            "x_axis_offset": hex(x_axis_offset) if x_axis_offset is not None else "N/A",
            "y_axis_offset": hex(y_axis_offset) if y_axis_offset is not None else "N/A",
            "x_axis": x_axis,
            "y_axis": y_axis,
            "unit": get_map_unit(map_type),
            "map": map_data
        })

    except Exception as e:
        logging.exception(f"Unhandled error during analysis for {map_type}.")
        return jsonify({"error": f"An unexpected error occurred during map analysis: {str(e)}. Please check log for details."}), 500

# === NEW ENDPOINT FOR SAVING TUNED BIN ===
@app.route("/save_tuned_bin", methods=["POST"])
def save_tuned_bin():
    if 'original_bin' not in request.files:
        logging.error("No original_bin file provided for saving.")
        return jsonify({"error": "No original .bin file provided"}), 400

    original_bin_file = request.files['original_bin']
    map_type = request.form.get("map_type")
    modified_map_data_str = request.form.get("modified_map_data")

    if not map_type or not modified_map_data_str:
        logging.error("Missing map_type or modified_map_data in save request.")
        return jsonify({"error": "Missing map type or modified data"}), 400

    if map_type not in MAP_OFFSETS:
        logging.error(f"Unsupported map type: '{map_type}' for saving.")
        return jsonify({"error": f"Unsupported map type: {map_type}. Please check MAP_OFFSETS configuration."}), 400

    try:
        modified_map_data = json.loads(modified_map_data_str)
        content = bytearray(original_bin_file.read()) # Use bytearray for mutability

        map_info = MAP_OFFSETS[map_type]
        block_offset = map_info["block"]
        rows, cols = map_info["size"]

        conv = MAP_CONVERSION_SETTINGS.get(map_type)
        if not conv:
            if map_type in ["pump_command", "injector_1", "injector_2", "limit_crp"]:
                conv = MAP_CONVERSION_SETTINGS["default_16bit"]
            else:
                conv = MAP_CONVERSION_SETTINGS["default_8bit"]
            logging.info(f"Using default conversion for '{map_type}' during save (no specific settings found).")

        data_type = conv["data_type"]
        factor = conv["factor"]
        offset_val = conv["offset"]
        endian = conv.get("endian")

        byte_per_value = 2 if data_type == "16bit" else 1
        total_map_bytes = rows * cols * byte_per_value

        # Check if the file is large enough to contain the map data block
        if block_offset + total_map_bytes > len(content):
            logging.error(f"Original file is too small to write map '{map_type}'. File size: {len(content)} bytes, Required end offset: {block_offset + total_map_bytes} bytes.")
            return jsonify({"error": "Original file too small to write map data. Check map block offset and size."}), 400

        # Convert modified map data back to raw bytes and overwrite
        for i in range(rows):
            for j in range(cols):
                tuned_value = modified_map_data[i][j]
                
                # Handle None values from frontend gracefully
                if tuned_value is None:
                    raw_tuned_value = 0 # Default to 0 if None. Consider a more appropriate default if needed for specific maps.
                    logging.warning(f"Tuned value for {map_type} at [{i},{j}] is None. Setting to raw 0 for conversion.")
                else:
                    # Reverse the conversion: raw = (value - offset) / factor
                    # เพิ่มการตรวจสอบ division by zero หาก factor เป็น 0
                    if factor == 0:
                        logging.error(f"Factor is 0 for {map_type}. Cannot reverse convert tuned value at [{i},{j}]. Setting to 0.")
                        raw_tuned_value = 0
                    else:
                        raw_tuned_value_float = (tuned_value - offset_val) / factor
                        
                        if data_type == "8bit":
                            raw_tuned_value = int(round(raw_tuned_value_float))
                            # Clamp 8-bit values to 0-255
                            raw_tuned_value = max(0, min(255, raw_tuned_value))
                        elif data_type == "16bit":
                            raw_tuned_value = int(round(raw_tuned_value_float))
                            # Clamp 16-bit values to 0-65535 (unsigned short)
                            raw_tuned_value = max(0, min(65535, raw_tuned_value))
                        else:
                            logging.error(f"Unknown data_type '{data_type}' during reverse conversion for {map_type}. Setting raw value to 0.")
                            return jsonify({"error": "Internal server error: Unknown data type for saving"}), 500


                start_idx = block_offset + (i * cols + j) * byte_per_value
                end_idx = start_idx + byte_per_value

                # ตรวจสอบขอบเขตการเขียนข้อมูล Map
                if end_idx > len(content):
                    logging.error(f"Attempted to write map '{map_type}' out of file bounds at offset {hex(start_idx)}. File length: {len(content)}. Data for [{i},{j}] skipped.")
                    # ไม่ return error ทันที ให้ process ต่อไปเผื่อมี map data ส่วนอื่นที่เขียนได้
                    continue

                if data_type == "8bit":
                    content[start_idx] = raw_tuned_value
                elif data_type == "16bit":
                    if endian is None:
                        logging.error(f"Endianness not specified for 16bit map '{map_type}' during save. Skipping write for [{i},{j}].")
                        continue
                    try:
                        packed_bytes = struct.pack(endian, raw_tuned_value)
                        content[start_idx:end_idx] = packed_bytes
                    except struct.error as se:
                        logging.error(f"Struct packing error for {map_type} at [{i},{j}]. Value: {raw_tuned_value}, Endian: {endian}. Error: {se}. Skipping write.")
                        continue
                
        # ======================================================================
        # !!! สำคัญมาก: LOGIC สำหรับการคำนวณและอัปเดต CHECKSUM !!!
        # ======================================================================
        # ส่วนนี้เป็นสิ่งสำคัญที่สุดที่คุณต้องเพิ่มเพื่อให้ไฟล์ที่จูนแล้ว
        # สามารถใช้งานได้จริงกับ ECU หากไม่มีการคำนวณ Checksum ที่ถูกต้อง
        # ECU จะถือว่าไฟล์เสียหายหรือไม่ถูกต้อง และจะไม่ยอมรับไฟล์นั้น
        #
        # คุณต้อง:
        # 1. ระบุ Algorithm ของ Checksum (เช่น CRC16, CRC32, Simple Sum, etc.)
        #    ที่ ECU รุ่นนี้ใช้.
        # 2. ระบุตำแหน่ง (Offset) ที่ Checksum ถูกเก็บไว้ในไฟล์.
        # 3. ระบุขอบเขต (Range) ของข้อมูลในไฟล์ .bin ที่ถูกนำไปคำนวณ Checksum.
        #
        # ตัวอย่าง (นี่คือ PSEUDOCODE คุณต้องเขียนฟังก์ชัน calculate_checksum() เอง):
        #
        # def calculate_checksum(data_bytes_segment):
        #     # Implement the specific checksum algorithm for your ECU here.
        #     # Example for a simple 16-bit sum:
        #     checksum = sum(data_bytes_segment) & 0xFFFF # Modulo 65536 for 16-bit
        #     return checksum
        #
        # if "your_ecu_model_identifier" in map_type: # อาจจะตรวจสอบจากชื่อ map หรือข้อมูลอื่น
        #     checksum_start_offset = 0x000000 # ตัวอย่าง: จุดเริ่มต้นของข้อมูลที่ Checksum ครอบคลุม
        #     checksum_end_offset = 0x1FFFFF   # ตัวอย่าง: จุดสิ้นสุดของข้อมูลที่ Checksum ครอบคลุม
        #     checksum_location_offset = 0x1FFFFC # ตัวอย่าง: ตำแหน่งที่เก็บค่า Checksum (เช่น 2 bytes)
        #
        #     if checksum_start_offset < len(content) and checksum_end_offset <= len(content) and checksum_location_offset + 2 <= len(content):
        #         data_for_checksum = content[checksum_start_offset:checksum_end_offset]
        #         new_checksum_value = calculate_checksum(data_for_checksum)
        #
        #         # เขียน Checksum กลับลงไปในไฟล์ (สมมติว่าเป็น 16-bit Little-endian)
        #         content[checksum_location_offset:checksum_location_offset + 2] = struct.pack("<H", new_checksum_value)
        #         logging.info(f"Checksum updated to {hex(new_checksum_value)} at {hex(checksum_location_offset)} for {map_type}.")
        #     else:
        #         logging.warning(f"Checksum calculation skipped for {map_type} due to invalid offsets/bounds.")
        # else:
        #     logging.warning(f"No specific checksum logic found for {map_type}. File might be invalid for ECU if checksum is required.")
        #
        # ======================================================================

        # ส่งไฟล์ที่แก้ไขแล้วกลับไป
        modified_file_stream = io.BytesIO(content)
        modified_file_stream.seek(0)

        logging.info(f"Successfully tuned and prepared file for {map_type}.")
        return send_file(
            modified_file_stream,
            mimetype='application/octet-stream',
            as_attachment=True,
            download_name=f"{map_type}_tuned_map.bin"
        )

    except json.JSONDecodeError as jde:
        logging.error(f"JSON Decode Error for modified_map_data: {jde}")
        return jsonify({"error": f"Invalid modified map data format: {str(jde)}"}), 400
    except struct.error as se:
        logging.error(f"Struct packing error during save for {map_type}: {se}")
        return jsonify({"error": f"Data packing error during save: {str(se)}"}), 500
    except Exception as e:
        logging.exception(f"Unhandled error during save_tuned_bin for {map_type}.")
        return jsonify({"error": f"An unexpected error occurred during saving: {str(e)}. Please check log for details."}), 500

if __name__ == '__main__':
    # สำหรับการรันบน Render/Production ไม่จำเป็นต้องใช้บรรทัดนี้ เพราะ Render จะจัดการการรันให้
    # หากรันในเครื่องเพื่อทดสอบ ให้ uncomment บรรทัดนี้
    app.run(host='0.0.0.0', port=10000, debug=True)

