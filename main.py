from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os
import struct # *** เพิ่มการ import struct เข้ามา ***
from werkzeug.middleware.proxy_fix import ProxyFix

# สร้าง Flask App
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# --- การตั้งค่า Conversion Factors และ Offsets สำหรับแต่ละ Map ---
# **สำคัญ:** สำหรับ 16-bit Map, ค่า 'factor' และ 'offset' จะแตกต่างออกไป
# ตัวอย่าง: ถ้าค่าดิบ 16-bit สูงสุด (65535) ควรแปลงเป็น 2500 บาร์ (สูงสุดของแรงดันราง)
# Factor จะประมาณ 2500 / 65535 = 0.03814697
MAP_CONVERSION_SETTINGS = {
    # Fuel Map: 8-bit (สมมติ)
    "fuel": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "torque_limiter": {"data_type": "8bit", "factor": 0.5, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "drivers_wish": {"data_type": "8bit", "factor": 0.5, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "fuel_quantity": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "injection_timing": {"data_type": "8bit", "factor": 0.0234375, "offset": -10.0, "x_scale": 1.0, "y_scale": 20.0},
    "boost_pressure": {"data_type": "8bit", "factor": 0.015625, "offset": 800, "x_scale": 1.0, "y_scale": 20.0},
    
    # Rail Pressure: ปรับเป็น 16-bit
    # **ใช้ค่า Factor และ Offset ที่ได้จากโปรแกรมจูนกล่อง ECU สำหรับ 16-bit Map ของคุณ**
    # **ค่าตัวอย่าง: 0.03814697 สำหรับ Factor (2500/65535), Offset 0**
    # **และระบุ 'endianness' ('>H' สำหรับ Big-endian, '<H' สำหรับ Little-endian)**
    "rail_pressure": {"data_type": "16bit", "factor": 0.03814697, "offset": 0, "endian": ">H", "x_scale": 1.0, "y_scale": 20.0}, 
    
    "turbo_duty": {"data_type": "8bit", "factor": 0.390625, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "smoke_limiter": {"data_type": "8bit", "factor": 0.01, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "iat_ect_correction": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "egr": {"data_type": "8bit", "factor": 0.390625, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "throttle": {"data_type": "8bit", "factor": 0.390625, "offset": 0, "x_scale": 1.0, "y_scale": 20.0},
    "dtc_off": {"data_type": "8bit", "factor": 1.0, "offset": 0, "x_scale": 1.0, "y_scale": 1.0}
}

# --- ตำแหน่ง Offset ของ Map Block และ แกน X/Y ในไฟล์ .bin ---
MAP_OFFSETS = {
    # Offset คงเดิม
    "fuel": {"block": 0x1D8710, "x_axis": 0x1D8610, "y_axis": 0x1D8600},
    "torque_limiter": {"block": 0x1DA000, "x_axis": 0x1D9F10, "y_axis": 0x1D9F00},
    "drivers_wish": {"block": 0x1DB000, "x_axis": 0x1DAF10, "y_axis": 0x1DAF00},
    "fuel_quantity": {"block": 0x1DC000, "x_axis": 0x1DBF10, "y_axis": 0x1DBF00},
    "injection_timing": {"block": 0x1DD000, "x_axis": 0x1DCF10, "y_axis": 0x1DCF00},
    "boost_pressure": {"block": 0x1DE000, "x_axis": 0x1DDF10, "y_axis": 0x1DDF00},
    "rail_pressure": {"block": 0x1DF000, "x_axis": 0x1DEF10, "y_axis": 0x1DEF00}, # Offset นี้คือจุดเริ่มต้นของ Map
    "turbo_duty": {"block": 0x1E0000, "x_axis": 0x1DFF10, "y_axis": 0x1DFF00},
    "smoke_limiter": {"block": 0x1E1000, "x_axis": 0x1E0F10, "y_axis": 0x1E0F00},
    "iat_ect_correction": {"block": 0x1E2000, "x_axis": 0x1E1F10, "y_axis": 0x1E1F00},
    "egr": {"block": 0x1E3000, "x_axis": 0x1E2F10, "y_axis": 0x1E2F00},
    "throttle": {"block": 0x1E4000, "x_axis": 0x1E3F10, "y_axis": 0x1E3F00},
    "dtc_off": {"block": 0x1F0000, "x_axis": 0x1EFF10, "y_axis": 0x1EFF00}
}

# ฟังก์ชันสำหรับแปลงค่าแกน X หรือ Y (มักจะเป็น 8-bit)
def parse_axis(raw_bytes, scale):
    """
    แปลงค่าดิบ (bytes) ของแกน X หรือ Y ให้เป็นค่าจริง
    :param raw_bytes: ข้อมูล byte ดิบจากไฟล์ .bin (16 bytes)
    :param scale: ตัวคูณสำหรับแปลงค่าดิบ
    :return: ลิสต์ของค่าแกนที่แปลงแล้ว
    """
    return [round(b * scale) for b in raw_bytes]

# Health Check Endpoint
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "ECU Map Analyzer"}), 200

# Error Handlers
@app.errorhandler(400)
def bad_request(e):
    app.logger.warning(f"Bad request: {str(e)}")
    return jsonify({"error": "Bad request"}), 400

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(413)
def request_too_large(e):
    app.logger.warning("Uploaded file exceeds size limit")
    return jsonify({"error": "File too large. Maximum size is 4MB"}), 413

@app.errorhandler(500)
def internal_error(e):
    app.logger.error(f"Internal server error: {str(e)}")
    return jsonify({"error": "Internal server error"}), 500

# Endpoint สำหรับวิเคราะห์ไฟล์ .bin
@app.route("/analyze", methods=["POST"])
def analyze_bin():
    """
    รับไฟล์ .bin และประเภทของ Map จาก Frontend
    อ่านข้อมูลจากไฟล์ตาม offset ที่กำหนด และแปลงเป็น 2D Map
    ส่งผลลัพธ์กลับในรูปแบบ JSON
    """
    if 'bin' not in request.files:
        app.logger.warning("No file part in request")
        return jsonify({"error": "No file uploaded"}), 400
        
    bin_file = request.files['bin']
    map_type = (request.form.get('type') or 'fuel').lower()

    if bin_file.filename == '':
        app.logger.warning("No selected file")
        return jsonify({"error": "No selected file"}), 400

    if map_type not in MAP_OFFSETS:
        app.logger.warning(f"Unsupported map type: {map_type}")
        return jsonify({"error": f"Unsupported map type: {map_type}"}), 400

    try:
        content = bin_file.read()
        offsets = MAP_OFFSETS[map_type]
        
        # ดึงการตั้งค่า Conversion รวมถึง data_type สำหรับ Map นี้
        conversion_settings = MAP_CONVERSION_SETTINGS.get(map_type, {
            "data_type": "8bit", # Default to 8-bit if not specified
            "factor": 1.0,
            "offset": 0,
            "x_scale": 1.0,
            "y_scale": 1.0
        })

        data_type = conversion_settings["data_type"]
        map_value_size = 2 if data_type == "16bit" else 1 # 2 bytes for 16-bit, 1 byte for 8-bit
        map_block_byte_size = 16 * 16 * map_value_size # ขนาดของ Map block ในหน่วย byte

        # ตรวจสอบขนาดไฟล์ที่จำเป็น
        max_offset_needed = max(
            offsets["block"] + map_block_byte_size, # ใช้ขนาด block ที่ถูกต้องตาม data_type
            offsets["x_axis"] + 16, # แกน X/Y มักเป็น 8-bit
            offsets["y_axis"] + 16
        )

        if len(content) < max_offset_needed:
            error_msg = (
                f"File too small for map '{map_type}' ({data_type}). "
                f"Required: {max_offset_needed} bytes, Got: {len(content)} bytes. "
                "Please ensure this is a valid ECU BIN file for this map type."
            )
            app.logger.error(error_msg)
            return jsonify({"error": error_msg}), 400

        # อ่านและแปลงแกน X/Y (คาดว่ายังคงเป็น 8-bit)
        x_raw = content[offsets["x_axis"]:offsets["x_axis"] + 16]
        y_raw = content[offsets["y_axis"]:offsets["y_axis"] + 16]
        x_axis = parse_axis(x_raw, conversion_settings["x_scale"])
        y_axis = parse_axis(y_raw, conversion_settings["y_scale"])

        # อ่าน Map data block
        block_raw_bytes = content[offsets["block"]:offsets["block"] + map_block_byte_size]
        
        factor = conversion_settings["factor"]
        offset_value = conversion_settings["offset"]
        
        map_2d = []
        for i in range(16):
            row = []
            for j in range(16):
                raw_value = 0 # ค่าเริ่มต้น
                
                if data_type == "8bit":
                    raw_value = block_raw_bytes[i * 16 + j]
                elif data_type == "16bit":
                    # คำนวณตำแหน่งเริ่มต้นของค่า 16-bit
                    byte_index = (i * 16 + j) * 2 
                    # ดึง 2 bytes สำหรับค่า 16-bit
                    value_bytes = block_raw_bytes[byte_index : byte_index + 2]
                    
                    if len(value_bytes) == 2:
                        try:
                            # ใช้ struct.unpack เพื่อแปลง bytes เป็น integer
                            # '>H' คือ Big-endian Unsigned Short (16-bit) - Common for automotive
                            # '<H' คือ Little-endian Unsigned Short (16-bit)
                            # **คุณต้องยืนยันว่า ECU ของคุณใช้ Endian แบบใด**
                            # ถ้าไม่แน่ใจ ลองเปลี่ยน '>H' เป็น '<H' ดู
                            raw_value = struct.unpack(conversion_settings["endian"], value_bytes)[0]
                        except struct.error as e:
                            app.logger.warning(f"Struct unpack error at byte_index {byte_index}: {e}. Defaulting to 0.")
                            raw_value = 0 # ตั้งค่าเริ่มต้นหากมีข้อผิดพลาดในการอ่าน
                    else:
                        app.logger.warning(f"Incomplete 16-bit value bytes at index {byte_index}. Got {len(value_bytes)} bytes.")
                        raw_value = 0 # กรณีข้อมูลไม่ครบ

                actual_value = (raw_value * factor) + offset_value
                row.append(round(actual_value, 2))
            map_2d.append(row)

        app.logger.info(f"Successfully analyzed '{map_type}' map ({data_type}). Dimensions: 16x16")
        
        return jsonify({
            "type": map_type,
            "offset": hex(offsets["block"]),
            "x_axis": x_axis,
            "y_axis": y_axis,
            "map": map_2d
        })
    
    except Exception as e:
        app.logger.exception(f"Error processing {map_type} map")
        return jsonify({
            "error": f"Processing error: {str(e)}",
            "map_type": map_type
        }), 500

# รัน Flask App
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    
    if not debug_mode:
        try:
            from waitress import serve
            app.logger.info(f"Starting PRODUCTION server on port {port}")
            serve(app, host="0.0.0.0", port=port)
        except ImportError:
            app.logger.warning("Waitress not found. Using built-in server")
            app.run(host="0.0.0.0", port=port, debug=False)
    else:
        app.logger.info(f"Starting DEVELOPMENT server on port {port}")
        app.run(host="0.0.0.0", port=port, debug=True)

