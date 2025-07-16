from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

# กำหนด Conversion Factors และ Offsets สำหรับแต่ละ Map
# ค่าเหล่านี้เป็นค่าประมาณการณ์จากข้อมูลทั่วไปของ ECU ที่คล้ายกัน
# คุณอาจต้องปรับค่า 'factor' และ 'offset' ให้ตรงกับ ECU ของ Isuzu D-Max 1.9L ของคุณจริงๆ
MAP_CONVERSION_SETTINGS = {
    "fuel": {"factor": 0.01, "offset": 0}, # มิลลิกรัม/จังหวะ (ตัวอย่าง)
    "torque_limiter": {"factor": 0.5, "offset": 0}, # นิวตันเมตร (ตัวอย่าง)
    "drivers_wish": {"factor": 0.5, "offset": 0}, # นิวตันเมตร (ตัวอย่าง)
    "fuel_quantity": {"factor": 0.01, "offset": 0}, # มิลลิเมตรกำลังสาม/จังหวะ (ตัวอย่าง)
    "injection_timing": {"factor": 0.0234375, "offset": -10.0}, # องศา BTDC (ตัวอย่าง)
    "boost_pressure": {"factor": 0.015625, "offset": 800}, # มิลลิบาร์ (ตัวอย่าง: ค่าดิบ 0 = 800mbar)
    "rail_pressure": {"factor": 9.765625, "offset": 0}, # บาร์: ค่าที่ถูกต้องสำหรับ 8-bit rail pressure map
    "turbo_duty": {"factor": 0.390625, "offset": 0}, # % Duty Cycle (ตัวอย่าง)
    "smoke_limiter": {"factor": 0.01, "offset": 0}, # มิลลิกรัม/จังหวะ (ตัวอย่าง)
    "iat_ect_correction": {"factor": 1.0, "offset": 0}, # ไม่มีหน่วย (ตัวอย่าง)
    "egr": {"factor": 0.390625, "offset": 0}, # % เปิด (ตัวอย่าง)
    "throttle": {"factor": 0.390625, "offset": 0}, # % เปิด (ตัวอย่าง)
    "dtc_off": {"factor": 1.0, "offset": 0} # ไม่มีหน่วย (ตัวอย่าง)
}

# ตำแหน่ง offset ของ Map block + แกน X/Y (เหมือนเดิม)
MAP_OFFSETS = {
    "fuel": { "block": 0x1D8710, "x_axis": 0x1D8610, "y_axis": 0x1D8600 },
    "torque_limiter": { "block": 0x1DA000, "x_axis": 0x1D9F10, "y_axis": 0x1D9F00 },
    "drivers_wish": { "block": 0x1DB000, "x_axis": 0x1DAF10, "y_axis": 0x1DAF00 },
    "fuel_quantity": { "block": 0x1DC000, "x_axis": 0x1DBF10, "y_axis": 0x1DBF00 },
    "injection_timing": { "block": 0x1DD000, "x_axis": 0x1DCF10, "y_axis": 0x1DCF00 },
    "boost_pressure": { "block": 0x1DE000, "x_axis": 0x1DDF10, "y_axis": 0x1DDF00 },
    "rail_pressure": { "block": 0x1DF000, "x_axis": 0x1DEF10, "y_axis": 0x1DEF00 },
    "turbo_duty": { "block": 0x1E0000, "x_axis": 0x1DFF10, "y_axis": 0x1DFF00 },
    "smoke_limiter": { "block": 0x1E1000, "x_axis": 0x1E0F10, "y_axis": 0x1E0F00 },
    "iat_ect_correction": { "block": 0x1E2000, "x_axis": 0x1E1F10, "y_axis": 0x1E1F00 },
    "egr": { "block": 0x1E3000, "x_axis": 0x1E2F10, "y_axis": 0x1E2F00 },
    "throttle": { "block": 0x1E4000, "x_axis": 0x1E3F10, "y_axis": 0x1E3F00 },
    "dtc_off": { "block": 0x1F0000, "x_axis": 0x1EFF10, "y_axis": 0x1EFF00 }
}

def parse_axis(raw_bytes, scale):
    # ปรับปรุง: แกน X/Y อาจมี Scale เฉพาะตัว
    # สำหรับ Isuzu D-Max 1.9L
    # แกน X (โหลด): ค่าดิบ * 0.01 (ถ้าเป็น % Load) หรือ 0.1
    # แกน Y (รอบเครื่อง): ค่าดิบ * 20 (ถ้าเป็น RPM)
    return [round(b * scale) for b in raw_bytes]

@app.route("/analyze", methods=["POST"])
def analyze_bin():
    bin_file = request.files.get('bin')
    map_type = (request.form.get('type') or 'fuel').lower()

    if not bin_file or map_type not in MAP_OFFSETS:
        return jsonify({ "error": "Missing file or unsupported map type" }), 400

    content = bin_file.read()
    offsets = MAP_OFFSETS[map_type]
    
    # ดึงค่า factor และ offset สำหรับ Map ที่เลือก
    conversion_settings = MAP_CONVERSION_SETTINGS.get(map_type, {"factor": 1.0, "offset": 0})
    factor = conversion_settings["factor"]
    offset_value = conversion_settings["offset"]

    try:
        # ตรวจสอบขนาดไฟล์ขั้นต่ำ
        # หากไฟล์เป็น 2MB (2097152 bytes) ควรมีการเช็ค offset สูงสุด
        max_required_offset = max(
            offsets["block"] + 256,
            offsets["x_axis"] + 16,
            offsets["y_axis"] + 16
        )
        if len(content) < max_required_offset:
            return jsonify({ "error": f"File too small for expected offset. Minimum size: {max_required_offset} bytes, but got {len(content)} bytes." }), 400

        # อ่านแกน X/Y: 16 bytes ต่อแกน
        # แกน X (โหลด) มักจะใช้ scale 1.0 หรือ 0.01 หากเป็นค่า percentage
        x_raw = content[offsets["x_axis"] : offsets["x_axis"] + 16]
        # แกน Y (รอบเครื่อง) มักจะใช้ scale 20.0 สำหรับ RPM (ค่าดิบ 1 = 20 RPM)
        y_raw = content[offsets["y_axis"] : offsets["y_axis"] + 16]

        x_axis = parse_axis(x_raw, scale=1.0) # ตรวจสอบ scale ที่ถูกต้องสำหรับแกน X (อาจจะเป็น 0.01 หรือ 0.1 สำหรับ %)
        y_axis = parse_axis(y_raw, scale=20.0) # ค่า 20.0 สำหรับ RPM ค่อนข้างพบบ่อย

        # อ่าน map block 256 bytes → 16×16
        block = content[offsets["block"] : offsets["block"] + 256]
        
        # ใช้ factor และ offset_value ที่ดึงมาสำหรับ Map ปัจจุบัน
        map_2d = [[round((b * factor) + offset_value, 2) for b in block[i*16:(i+1)*16]] for i in range(16)]

        return jsonify({
            "type": map_type.capitalize(),
            "offset": hex(offsets["block"]),
            "x_axis": x_axis,
            "y_axis": y_axis,
            "map": map_2d
        })
    
    except Exception as e:
        app.logger.error(f"Processing error: {str(e)}")
        return jsonify({ "error": f"Processing error: {str(e)}" }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

